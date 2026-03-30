import asyncio
import subprocess
import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

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
    
    audio_filename = f"meeting_audio_{int(time.time())}.wav"
    temp_audio_filename = f"meeting_audio_{int(time.time())}_temp.wav"
    ffmpeg_process = None
    driver = None

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
        time.sleep(3) # Let the camera initialize
        
        try:
            join_btn = driver.find_element(By.XPATH, "//button[contains(., 'Ask to join') or contains(., 'Join now')]")
            join_btn.click()
            print("[BOT] ✅ Clicked 'Ask to Join'!")
        except Exception as e:
            print("[BOT] ❌ Failed to click join button.")
            _save_screenshot(driver, "error_join_click")
            raise e

        # === STEP 5: Wait for Admission ===
        print("[BOT] ⏳ Waiting to be admitted... Please admit from host account! (60s timeout)")
        wait = WebDriverWait(driver, 60)
        # We know we are inside when the red "Leave call" button appears
        wait.until(EC.presence_of_element_located((By.XPATH, "//button[@aria-label='Leave call']")))
        print("[BOT] ✅ Admitted to the meeting!")

        # === STEP 6: Start FFmpeg Recording ===
        print("[BOT] 🎙️ Starting FFmpeg audio capture...")
        ffmpeg_cmd = [
            "ffmpeg", "-f", "pulse", "-i", "default", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", temp_audio_filename, "-y"
        ]
        ffmpeg_process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # === STEP 7: Monitor Meeting Status ===
        print("[BOT] 📍 Monitoring meeting status. Will record until meeting ends...")
        meeting_ended = False
        
        while not meeting_ended:
            time.sleep(5) # Check every 5 seconds
            try:
                # If we can still find the Leave Call button, we are still in the meeting
                driver.find_element(By.XPATH, "//button[@aria-label='Leave call']")
            except NoSuchElementException:
                print("[BOT] Meeting UI disappeared! Meeting has ended.")
                meeting_ended = True

        return audio_filename

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