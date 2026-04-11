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

    model = genai.GenerativeModel('models/gemini-2.5-flash')

    # Enhanced prompt for better, more user-friendly summaries
    prompt = """
You are a precise meeting summarizer. Your ONLY job is to extract and structure information that was EXPLICITLY stated in the meeting transcript or audio. You must NEVER infer, assume, or fabricate any information not directly present in the meeting.

Return ONLY a valid JSON object with this exact structure:
{
    "executive": "string",
    "actionItems": [
        {
            "assignee": "string",
            "task": "string",
            "priority": "high" | "medium" | "low"
        }
    ],
    "duration": "string",
    "participants": ["string"]
}

---

FIELD-BY-FIELD RULES:

[executive]
- Write 3–4 sentences maximum. No filler, no repetition.
- Sentence 1: What was the PRIMARY topic or goal of the meeting?
- Sentence 2: What KEY decisions or conclusions were reached?
- Sentence 3: What blockers, risks, or unresolved issues were raised?
- Sentence 4 (only if needed): Any notable next steps or dependencies mentioned.
- Do NOT restate action items here — they belong in actionItems only.
- Do NOT use vague phrases like "various topics were discussed" or "several points were made."
- Every sentence must carry unique, non-overlapping information.

[actionItems]
- Include ONLY tasks explicitly committed to or assigned during the meeting.
- Each task must answer: WHO will do WHAT by WHEN (include deadline only if explicitly stated).
- Do NOT split one task into multiple items — keep related sub-tasks under a single entry.
- Do NOT duplicate tasks that are restatements of the same commitment.
- Do NOT include tasks that were merely suggested or discussed without clear ownership.
- "assignee": Use the speaker's name if identified. If unidentifiable, use "Speaker 1", "Speaker 2", etc. If truly unassigned, use "Unassigned".
- "priority":
    - "high" → explicit deadline mentioned OR described as urgent/critical in the meeting
    - "medium" → standard work with no special urgency indicated
    - "low" → optional, nice-to-have, or explicitly deprioritized
- If no action items were committed to, return: []

[duration]
- Use only what can be inferred from timestamps or explicit mentions in the transcript.
- If unknown, return: "Unknown"
- Format: "X minutes" or "X hours Y minutes"

[participants]
- List only speakers who actually spoke or were directly addressed by name.
- Use real names if identifiable, otherwise "Speaker 1", "Speaker 2", etc.
- Do NOT include people merely mentioned in passing.

---

STRICT RULES (apply to entire output):
1. GROUND TRUTH ONLY — Every piece of information must come directly from the meeting content. No assumptions.
2. NO HALLUCINATION — If something is unclear or unsaid, omit it rather than guess.
3. NO REDUNDANCY — Each fact, task, or point must appear exactly once across the entire JSON.
4. NO FILLER — Avoid generic phrases that add length without meaning.
5. Return ONLY the raw JSON object. No markdown, no explanation, no wrapper text.
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