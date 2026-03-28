import boto3
import os
import json
import re
from typing import Optional, Tuple
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BUCKET_NAME = os.environ.get("AWS_S3_BUCKET_NAME")
S3_FOLDER_PREFIX = os.environ.get("S3_FOLDER_PREFIX", "users")

# --- VALIDATION ---
def _validate_credentials() -> Tuple[bool, str]:
    """Validate AWS credentials and bucket configuration."""
    if not all([AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, BUCKET_NAME]):
        return False, "Missing AWS credentials or bucket name in environment variables"

    # Validate bucket name format (AWS S3 naming rules)
    if not re.match(r'^[a-z0-9.-]{3,63}$', BUCKET_NAME):
        return False, f"Invalid S3 bucket name: {BUCKET_NAME}"

    return True, ""

def _sanitize_path_component(component: str) -> str:
    """Sanitize strings to be safe for use in S3 object keys."""
    # Allow only alphanumeric, dots, hyphens, and underscores
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '_', component)
    return sanitized[:64]  # Limit length

# Initialize the S3 client securely using your .env variables
s3_client = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION
)


def upload_to_s3(job_id: str, user_id: str, summary_data: dict, audio_file_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Uploads the JSON summary and the raw audio file to AWS S3.
    Organizes files into folders based on the user's ID.

    Args:
        job_id: Unique identifier for the job
        user_id: User identifier for folder organization
        summary_data: Dictionary containing meeting summary data
        audio_file_path: Optional path to the audio file to upload

    Returns:
        Tuple of (success: bool, message: str)
        - On success: (True, "Upload successful")
        - On failure: (False, error_description)
    """
    # Validate credentials and configuration
    is_valid, error_msg = _validate_credentials()
    if not is_valid:
        return False, f"Configuration error: {error_msg}"

    # Sanitize inputs to prevent path traversal
    safe_user_id = _sanitize_path_component(user_id)
    safe_job_id = _sanitize_path_component(job_id)

    try:
        # 1. Upload the JSON summary
        json_key = f"{S3_FOLDER_PREFIX}/{safe_user_id}/{safe_job_id}_summary.json"

        s3_client.put_object(
            Bucket=BUCKET_NAME,
            Key=json_key,
            Body=json.dumps(summary_data, indent=2),
            ContentType='application/json'
        )
        print(f"[S3] ✅ Summary uploaded to: {json_key}")

        # 2. Upload the Audio file (if provided)
        if audio_file_path:
            if not os.path.exists(audio_file_path):
                return False, f"Audio file not found: {audio_file_path}"

            audio_key = f"{S3_FOLDER_PREFIX}/{safe_user_id}/{safe_job_id}_audio.wav"
            s3_client.upload_file(
                Filename=audio_file_path,
                Bucket=BUCKET_NAME,
                Key=audio_key
            )
            print(f"[S3] ✅ Audio uploaded to: {audio_key}")

            # Clean up the local audio file after upload to save disk space
            os.remove(audio_file_path)
            print(f"[LOCAL] Cleaned up temporary audio file: {audio_file_path}")

        return True, "Upload successful"

    except (BotoCoreError, ClientError) as e:
        error_detail = str(e)
        print(f"[S3] ❌ AWS error: {error_detail}")
        return False, f"AWS S3 error: {error_detail}"
    except json.JSONEncodeError as e:
        return False, f"Failed to serialize summary data: {e}"
    except Exception as e:
        print(f"[S3] ❌ Unexpected error: {e}")
        return False, f"Unexpected error: {e}"