from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import asyncio
import uuid
import threading
import firebase_admin
from firebase_admin import credentials, auth
from meet_boot import join_meet_and_record
from ai_summary import generate_meeting_summary
from cloud_storage import upload_to_s3


# --- FIREBASE SETUP ---
cred = credentials.Certificate("firebase-credentials.json")
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)


app = FastAPI(title="Google Meet AI Scribe API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ai-scribe-21776.web.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- IN-MEMORY DATABASE ---
jobs_db: Dict[str, Any] = {}

# --- PYDANTIC MODELS ---
class MeetRequest(BaseModel):
    url: str

class JobInitResponse(BaseModel):
    job_id: str
    status: str
    message: str

class ActionItem(BaseModel):
    assignee: str
    task: str
    priority: str

class SummaryResponse(BaseModel):
    executive: str
    actionItems: List[ActionItem]
    duration: str
    participants: List[str]
    audioFile: Optional[str] = None


# --- AUTHENTICATION DEPENDENCY ---
async def get_current_user(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header. Please sign in.")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format. Use: Bearer <token>")

    token = parts[1]
    try:
        decoded_token = auth.verify_id_token(token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email"),
            "name": decoded_token.get("name"),
            "picture": decoded_token.get("picture")
        }
    except auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token expired. Please sign in again.")
    except auth.InvalidIdTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# --- THE BACKGROUND WORKER ---
async def process_meeting_task(job_id: str, meet_url: str):
    try:
        print(f"[JOB {job_id}] Bot deploying to {meet_url}...")
        jobs_db[job_id]["status"] = "recording"

        # Pass the stop_event so the bot can be stopped by the user
        stop_event = jobs_db[job_id]["stop_event"]
        audio_file = await join_meet_and_record(meet_url, stop_event=stop_event)

        if not audio_file:
            jobs_db[job_id]["status"] = "failed"
            jobs_db[job_id]["error"] = "Failed to record meeting audio"
            return

        print(f"[JOB {job_id}] Recording finished. Generating summary...")
        jobs_db[job_id]["status"] = "processing"

        try:
            summary = generate_meeting_summary(audio_file)
        except Exception as ai_error:
            print(f"[JOB {job_id}] AI summary failed: {ai_error}")
            summary = {
                "executive": "Meeting was recorded but AI summary generation failed.",
                "actionItems": [],
                "duration": "Unknown",
                "participants": []
            }

        success, msg = upload_to_s3(
            job_id=job_id,
            user_id=jobs_db[job_id]["user_id"],
            summary_data=summary,
            audio_file_path=audio_file
        )
        if not success:
            print(f"[JOB {job_id}] S3 upload failed: {msg}")

        jobs_db[job_id]["status"] = "completed"
        jobs_db[job_id]["result"] = summary
        print(f"[JOB {job_id}] ✅ Complete!")

    except Exception as e:
        print(f"[JOB {job_id}] ❌ Error: {str(e)}")
        jobs_db[job_id]["status"] = "failed"
        jobs_db[job_id]["error"] = str(e)


# --- API ENDPOINTS ---

@app.post("/deploy-bot", response_model=JobInitResponse)
async def deploy_bot(
    request: MeetRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["uid"]
    user_email = current_user.get("email", "unknown")
    print(f"[AUTH] User {user_email} ({user_id}) is deploying bot")

    if "meet.google.com" not in request.url:
        raise HTTPException(status_code=400, detail="Invalid Google Meet URL")

    job_id = str(uuid.uuid4())

    # Create a stop_event for this job — set it to stop the bot early
    stop_event = threading.Event()

    jobs_db[job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "user_email": user_email,
        "status": "pending",
        "url": request.url,
        "result": None,
        "error": None,
        "stop_event": stop_event,       # threading.Event — set to stop the bot
        "stop_requested": False,        # Readable flag for the frontend
    }

    background_tasks.add_task(process_meeting_task, job_id, request.url)

    return JobInitResponse(
        job_id=job_id,
        status="pending",
        message="Bot deployment initiated."
    )


@app.post("/stop-bot/{job_id}")
async def stop_bot(job_id: str, current_user: dict = Depends(get_current_user)):
    """
    User-triggered stop: signals the bot to leave the meeting cleanly,
    then the summary is generated as normal.
    """
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs_db[job_id]

    # Security: only the owner can stop their own bot
    if job["user_id"] != current_user["uid"]:
        raise HTTPException(status_code=403, detail="Not authorized to stop this job")

    if job["status"] not in ("pending", "recording"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot stop job in '{job['status']}' state"
        )

    # Signal the bot's monitoring loop to exit
    job["stop_event"].set()
    job["stop_requested"] = True

    print(f"[JOB {job_id}] 🛑 Stop requested by user {current_user.get('email')}")

    return {"message": "Stop signal sent. Bot will leave and generate summary shortly."}


@app.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs_db[job_id]

    # Don't expose the threading.Event object to the frontend
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "result": job.get("result"),
        "error": job.get("error"),
        "stop_requested": job.get("stop_requested", False),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)