import asyncio
import subprocess
import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# --- CONFIGURATION ---
DEBUG_DIR = "debug_screenshots"

def _save_screenshot(driver, name):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, f"{name}.png")
        driver.save_screenshot(filepath)
    except Exception as e:
        print(f"[BOT] Screenshot failed ({name}): {e}")

def _run_bot_sync(meet_url: str, bot_name: str = "AI Scribe Bot"):
    """
    Synchronous bot function that uses Selenium + undetected-chromedriver.
    """
    # Ensure Xvfb virtual monitor is linked
    os.environ["DISPLAY"] = ":99"

    timestamp = int(time.time())
    audio_filename = f"meeting_audio_{timestamp}.wav"
    temp_audio_filename = f"meeting_audio_{timestamp}_temp.wav"
    ffmpeg_process = None
    driver = None
    is_recording = False

    print(f"[BOT] ═══════════════════════════════════════")
    print(f"[BOT] Starting bot for: {meet_url}")
    print(f"[BOT] ═══════════════════════════════════════")

    try:
        # === STEP 1: Launch Chrome ===
        print("[BOT] Launching Chrome...")
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--use-fake-device-for-media-stream")

        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 1,
        })

        # --- AUTO-DETECT CHROME VERSION ---
        chrome_version = None
        chrome_binary = "/usr/bin/google-chrome" # Standard Ubuntu path
        
        if os.path.exists(chrome_binary):
            try:
                version_output = subprocess.check_output([chrome_binary, "--version"]).decode('utf-8').strip()
                # Output like: "Google Chrome 146.0.7680.164"
                chrome_version = int(version_output.split()[-1].split(".")[0])
                print(f"[BOT] Auto-detected Chrome version: {chrome_version}")
            except Exception as e:
                print(f"[BOT] Failed to detect Chrome version: {e}")
        else:
            print(f"[BOT] Chrome binary not found at {chrome_binary}. Letting UC auto-detect.")
            chrome_binary = None

        options.add_argument("--lang=en-US")

        driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            browser_executable_path=chrome_binary,
            version_main=chrome_version
        )
        
        driver.implicitly_wait(10) # Tell Selenium to wait up to 10 seconds for elements to appear
        print("[BOT] ✅ Chrome launched")

        # === STEP 2: Navigate ===
        print("[BOT] Navigating to meeting...")
        driver.get(meet_url)
        time.sleep(4)

        # === STEP 3: Enter Name ===
        print("[BOT] Looking for name input...")
        try:
            name_input = driver.find_element(By.XPATH, "//input[@placeholder='Your name' or @aria-label='Your name']")
            name_input.send_keys(bot_name)
            print("[BOT] ✅ Name entered")
            time.sleep(1)
        except NoSuchElementException:
            print("[BOT] No name input found (might be logged in). Skipping...")

        # === STEP 4: Ask to Join ===
        print("[BOT] Locating 'Ask to join' button...")
        time.sleep(3) 
        
        try:
            join_btn = driver.find_element(By.XPATH, "//button[contains(., 'Ask to join') or contains(., 'Join now')]")
            join_btn.click()
            print("[BOT] ✅ Clicked 'Ask to Join'!")
        except Exception as e:
            print("[BOT] ❌ Failed to click join button.")
            raise e

        # === STEP 4.5: START RECORDING EARLY (Your Strategy) ===
        print("[BOT] 🎙️ Starting early FFmpeg audio capture from lobby...")
        # Ensure your AWS server has a virtual pulse audio sink running!
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", temp_audio_filename, "-y"
        ]
        ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        is_recording = True

        # === STEP 5: Wait for Admission ===
        print("[BOT] ⏳ Waiting to be admitted... (120s timeout)")
        
        in_meeting = False
        for attempt in range(60): # 60 attempts * 2s = 120 seconds max
            time.sleep(2)
            
            # Check 1: Did the URL change away from the meeting link entirely?
            if "meet.google.com" not in driver.current_url:
                print("[BOT] 🛑 Booted from Meet URL while waiting.")
                break

            # Check 2: Look for the Leave Call button (Primary signal)
            try:
                leave_btn = driver.find_element(By.XPATH, "//button[@aria-label='Leave call']")
                if leave_btn.is_displayed():
                    print("[BOT] ✅ Officially admitted to the meeting!")
                    in_meeting = True
                    break
            except NoSuchElementException:
                pass # Still in lobby

        if not in_meeting:
            print("[BOT] 🛑 Timeout or rejected from meeting. Stopping early record.")
            ffmpeg_process.terminate()
            return None

        # === STEP 6: Monitor Meeting for End/Kick ===
        print("[BOT] 📍 Recording active. Monitoring for meeting end...")
        
        # Hard timeout safeguard (e.g., 2 hours max)
        max_duration = 7200 
        start_time = time.time()

        while True:
            time.sleep(3) # Check every 3 seconds
            
            # Condition A: Hard Timeout
            if time.time() - start_time > max_duration:
                print("[BOT] 🛑 Reached maximum meeting duration. Exiting.")
                break

            # Condition B: URL changed to the exit screen
            current_url = driver.current_url
            if "/left" in current_url or "meet.google.com" not in current_url:
                print("[BOT] 🛑 URL indicates meeting has ended.")
                break

            # Condition C: Check page source for kick/end messages
            # This catches "You've been removed" or "The meeting has ended" text
            page_text = driver.page_source.lower()
            if "you've been removed" in page_text or "left the meeting" in page_text or "return to home screen" in page_text:
                print("[BOT] 🛑 Detected meeting end text on screen.")
                break

            # Condition D: The leave button vanished
            try:
                driver.find_element(By.XPATH, "//button[@aria-label='Leave call']")
            except NoSuchElementException:
                print("[BOT] 🛑 Leave button disappeared. Meeting likely ended.")
                break

        # === STEP 7: Stop Recording and Save ===
        if ffmpeg_process and is_recording:
            print("[BOT] 🛑 Stopping FFmpeg recording...")
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
            is_recording = False

            if os.path.exists(temp_audio_filename):
                os.rename(temp_audio_filename, audio_filename)
                print(f"[BOT] ✅ Audio saved to {audio_filename}. Ready for LLM processing.")
                
        return audio_filename

        # # === STEP 8: Stop Recording ===
        # if ffmpeg_process and is_recording:
        #     print("[BOT] 🛑 Stopping FFmpeg recording...")
        #     ffmpeg_process.terminate()
        #     ffmpeg_process.wait()
        #     is_recording = False

        #     # Rename temp file to final file
        #     if os.path.exists(temp_audio_filename):
        #         os.rename(temp_audio_filename, audio_filename)
        #         print(f"[BOT] ✅ Audio saved to {audio_filename}")

        # return audio_filename

    except Exception as e:
        print(f"[BOT] ❌ An error occurred: {e}")
        if driver:
            _save_screenshot(driver, "fatal_error")
        return None

    finally:
        # === CLEANUP ===
        if ffmpeg_process:
            print("[BOT] Stopping recording...")
            ffmpeg_process.terminate()
            ffmpeg_process.wait()
            
            # Save the final file
            if os.path.exists(temp_audio_filename):
                os.rename(temp_audio_filename, audio_filename)
                print(f"[BOT] ✅ Audio saved to {audio_filename}")
                
        if driver:
            print("[BOT] Closing browser...")
            driver.quit()

# === ASYNC WRAPPER FOR FASTAPI ===
async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot"):
    return await asyncio.to_thread(_run_bot_sync, meet_url, bot_name)

# --- Test Execution ---
if __name__ == "__main__":
    test_url = input("Paste a Google Meet link to test: ")
    asyncio.run(join_meet_and_record(test_url))