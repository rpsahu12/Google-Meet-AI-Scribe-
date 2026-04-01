from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import asyncio
import uuid # For generating unique Job IDs
import firebase_admin
from firebase_admin import credentials, auth
from meet_boot import join_meet_and_record
from ai_summary import generate_meeting_summary
from cloud_storage import upload_to_s3  # Returns Tuple[bool, str]


# --- FIREBASE SETUP ---
cred = credentials.Certificate("firebase-credentials.json")
# Check if Firebase is already initialized to prevent hot-reload crashes
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)


# Initialize the FastAPI app
app = FastAPI(title="Google Meet AI Scribe API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- IN-MEMORY DATABASE ---
# For this MVP, we store jobs in a dictionary. 
# In a real enterprise app, you would use Redis or PostgreSQL here.
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
    """
    Security guard: Verifies Firebase ID token from Authorization header.
    Expects: "Bearer <firebase_id_token>"
    Returns: decoded user info (including user_id)
    """
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Missing authorization header. Please sign in."
        )

    # Extract token from "Bearer <token>" format
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization format. Use: Bearer <token>"
        )

    token = parts[1]

    try:
        # Verify token against Google's servers
        decoded_token = auth.verify_id_token(token)
        return {
            "uid": decoded_token["uid"],
            "email": decoded_token.get("email"),
            "name": decoded_token.get("name"),
            "picture": decoded_token.get("picture")
        }
    except auth.ExpiredTokenError:
        raise HTTPException(status_code=401, detail="Token expired. Please sign in again.")
    except auth.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


# --- THE BACKGROUND WORKER ---
async def process_meeting_task(job_id: str, meet_url: str):
    """This function runs in the background while the API immediately responds to the user."""
    try:
        print(f"[JOB {job_id}] Bot deploying to {meet_url}...")
        jobs_db[job_id]["status"] = "recording"

        # 1. Run the bot (stays until meeting ends)
        audio_file = await join_meet_and_record(meet_url)

        if not audio_file:
            jobs_db[job_id]["status"] = "failed"
            jobs_db[job_id]["error"] = "Failed to record meeting audio"
            return

        # 2. Moving to AI processing phase
        print(f"[JOB {job_id}] Recording finished. Generating summary...")
        jobs_db[job_id]["status"] = "processing"

        # 3. Generate Summary using Gemini AI
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

        # 4. Upload to S3 (storage happens before marking complete)
        success, msg = upload_to_s3(
            job_id=job_id,
            user_id=jobs_db[job_id]["user_id"],
            summary_data=summary,
            audio_file_path=audio_file
        )
        if not success:
            print(f"[JOB {job_id}] S3 upload failed: {msg}")
            # Don't fail the job - summary is still available locally

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
    """
    Endpoint 1: Instantly start the job and return the ID.
    Requires Firebase authentication via Authorization header.
    """
    # Security guard: User is already verified by get_current_user dependency
    user_id = current_user["uid"]
    user_email = current_user.get("email", "unknown")
    print(f"[AUTH] User {user_email} ({user_id}) is deploying bot")

    if "meet.google.com" not in request.url:
        raise HTTPException(status_code=400, detail="Invalid Google Meet URL")

    # 1. Generate a unique ID for this session
    job_id = str(uuid.uuid4())

    # 2. Create the job record in our "database" with user info
    jobs_db[job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "user_email": user_email,
        "status": "pending", # States: pending -> recording -> processing -> completed/failed
        "url": request.url,
        "result": None,
        "error": None
    }

    # 3. Pass the heavy lifting to the background task
    background_tasks.add_task(process_meeting_task, job_id, request.url)

    # 4. Instantly reply to React so the browser doesn't time out
    return JobInitResponse(
        job_id=job_id,
        status="pending",
        message="Bot deployment initiated."
    )

@app.get("/job-status/{job_id}")
async def get_job_status(job_id: str):
    """Endpoint 2: React will poll this endpoint every few seconds to check progress."""
    if job_id not in jobs_db:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return jobs_db[job_id]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)