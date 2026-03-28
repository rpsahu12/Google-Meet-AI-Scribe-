import google.generativeai as genai
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

def generate_meeting_summary(audio_file_path: str):
    """
    Uploads the audio file to Gemini, prompts it for a structured JSON summary,
    and returns the parsed dictionary.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing!")

    genai.configure(api_key=api_key)

    print(f"[AI] Uploading {audio_file_path} to Gemini...")
    audio_file = genai.upload_file(path=audio_file_path)

    # Audio processing can take a few seconds on Google's end
    # Add timeout to prevent infinite waiting
    max_wait_time = 120  # 2 minutes max
    start_time = time.time()

    while audio_file.state.name == "PROCESSING":
        elapsed = time.time() - start_time
        if elapsed > max_wait_time:
            print(f"[AI] Processing timeout after {max_wait_time}s")
            genai.delete_file(audio_file.name)
            raise TimeoutError(f"Audio processing timed out after {max_wait_time} seconds")

        print(f"[AI] Waiting for audio processing... ({elapsed:.1f}s elapsed)")
        time.sleep(2)
        audio_file = genai.get_file(audio_file.name)

    print("[AI] Audio ready. Generating summary...")

    model = genai.GenerativeModel('models/gemini-1.5-flash')

    # Enhanced prompt for better, more user-friendly summaries
    prompt = """
    You are an expert meeting assistant. Analyze the provided meeting audio and create a clear, actionable summary.

    Return ONLY a valid JSON object with this exact structure:
    {
        "executive": "A clear, 3-4 sentence executive summary highlighting key decisions, main topics, and outcomes. Write in a professional, easy-to-scan style.",
        "actionItems": [
            {"assignee": "Person's name or 'Unassigned'", "task": "Specific, actionable task description", "priority": "high" or "medium" or "low"}
        ],
        "duration": "Estimated meeting duration (e.g., '15 minutes', '1 hour 30 minutes')",
        "participants": ["List", "of", "identified", "speakers"]
    }

    Guidelines:
    - Executive summary: Focus on WHAT was discussed, WHAT was decided, and ANY blockers
    - Action items: Extract ALL commitments made, be specific about what needs to be done
    - Priority: Mark as 'high' if deadline mentioned or critical task, 'medium' for normal work, 'low' for nice-to-haves
    - If no action items exist, return empty array []
    - If you cannot identify speaker names, use generic labels like 'Speaker 1', 'Speaker 2'
    """

    try:
        response = model.generate_content(
            [prompt, audio_file],
            generation_config={"response_mime_type": "application/json"}
        )

        summary_data = json.loads(response.text)

        # Validate required fields exist
        required_fields = ["executive", "actionItems", "duration", "participants"]
        for field in required_fields:
            if field not in summary_data:
                summary_data[field] = [] if field == "actionItems" or field == "participants" else "Not available"

        # Cleanup
        genai.delete_file(audio_file.name)

        print(f"[AI] Summary generated successfully")
        return summary_data

    except json.JSONDecodeError as e:
        print(f"[AI] Invalid JSON response: {e}")
        genai.delete_file(audio_file.name)
        raise ValueError(f"Failed to parse AI response as JSON: {e}")
    except Exception as e:
        print(f"[AI] Error during generation: {e}")
        genai.delete_file(audio_file.name)
        raise e