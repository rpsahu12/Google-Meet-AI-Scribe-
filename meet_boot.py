import asyncio
import subprocess
import os
import time
from playwright.async_api import async_playwright

async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot", record_seconds: int = 60):
    """
    Automates joining a Google Meet and records the raw audio using Ubuntu's PulseAudio.
    """
    # Create a unique filename based on timestamp
    audio_filename = f"meeting_audio_{int(time.time())}.wav"
    
    print(f"Starting bot for URL: {meet_url}")
    
    async with async_playwright() as p:
        # Launch Chromium. 
        # Note: We keep headless=False for now so you can see it working via X11/Wayland forwarding in WSL.
        # When deploying to AWS, we will wrap this script in `xvfb-run` to handle the virtual display.
        browser = await p.chromium.launch(
            headless=False, 
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--disable-features=AudioServiceOutOfProcess", # Forces audio to system pulse/alsa
                "--disable-blink-features=AutomationControlled"
            ]
        )
        
        context = await browser.new_context(permissions=['camera', 'microphone'])
        page = await context.new_page()
        
        try:
            print("Navigating to meeting...")
            await page.goto(meet_url)
            
            # 1. Enter Name
            print("Typing bot name...")
            await page.wait_for_selector('input[type="text"]', timeout=15000)
            await page.fill('input[type="text"]', bot_name)
            
            # 2. Ask to Join
            print("Clicking 'Ask to join'. Please admit the bot from your host account!")
            await page.click('button:has-text("Ask to join"), button:has-text("Join now")')
            
            # 3. Wait for Admission (we check for the meeting details button which only appears inside)
            await page.wait_for_selector('button[aria-label="Meeting details"]', timeout=60000)
            print("Successfully admitted to the meeting!")
            
            # 4. Start Audio Recording
            print(f"🎙️ Starting FFmpeg audio capture for {record_seconds} seconds...")
            # This captures the default PulseAudio output (what the browser hears)
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "pulse",          # Input format: PulseAudio
                "-i", "default",        # Input source: Default audio sink
                "-t", str(record_seconds),
                "-acodec", "pcm_s16le", # WAV format
                "-ar", "16000",         # 16kHz (Optimal for speech-to-text models)
                "-ac", "1",             # Mono
                audio_filename,
                "-y"                    # Overwrite
            ]
            
            # Launch FFmpeg in the background
            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Wait while the meeting happens
            await asyncio.sleep(record_seconds)
            
            print("Recording complete. Wrapping up...")
            
            # Ensure FFmpeg closes properly
            process.terminate()
            process.wait()
            
            if os.path.exists(audio_filename):
                print(f"✅ Audio successfully saved to {audio_filename}")
                return audio_filename
            else:
                print("❌ Failed to save audio file.")
                return None
                
        except Exception as e:
            print(f"An error occurred: {e}")
            return None
            
        finally:
            print("Closing browser...")
            await browser.close()

# --- Test Execution ---
if __name__ == "__main__":
    # Create a dummy Google Meet manually, copy the link, and paste it here
    test_url = input("Paste a Google Meet link to test: ")
    asyncio.run(join_meet_and_record(test_url, record_seconds=30))