import asyncio
import subprocess
import os
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)

# --- CONFIGURATION ---
DEBUG_DIR = "debug_screenshots"
MAX_MEETING_DURATION = 7200  # 2 hours hard cap
ADMISSION_TIMEOUT = 120      # seconds to wait for host to admit bot


def _save_screenshot(driver, name):
    """Save a debug screenshot — call this aggressively while debugging."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, f"{name}.png")
        driver.save_screenshot(filepath)
        print(f"[BOT] 📸 Screenshot saved: {filepath}")
    except Exception as e:
        print(f"[BOT] Screenshot failed ({name}): {e}")


def _is_admitted(driver) -> bool:
    """
    Multi-signal check for whether the bot is inside the meeting.
    Google Meet's UI changes frequently, so we use 5 independent signals.
    Returns True if ANY signal fires.
    """
    # Signal 1: Classic Leave Call button (aria-label varies by language/version)
    leave_aria_labels = [
        "Leave call",
        "Leave meeting",
        "End call",
        "Hang up",
    ]
    for label in leave_aria_labels:
        try:
            btn = driver.find_element(By.XPATH, f"//button[@aria-label='{label}']")
            if btn.is_displayed():
                print(f"[BOT] ✅ Admission signal: found button aria-label='{label}'")
                return True
        except NoSuchElementException:
            pass

    # Signal 2: Data-call-ended attribute is absent — when you're IN a call,
    # Meet renders a container without this attribute
    try:
        # The participant tile grid only exists when you're in the meeting
        driver.find_element(By.XPATH, "//*[@data-participant-id]")
        print("[BOT] ✅ Admission signal: participant tile found")
        return True
    except NoSuchElementException:
        pass

    # Signal 3: URL pattern — Google Meet appends a room code after joining
    # Lobby URL: meet.google.com/abc-defg-hij
    # In-meeting URL: same but page state is different — check for subtler signals
    try:
        # The bottom toolbar with mic/camera controls only renders post-admission
        toolbar = driver.find_element(
            By.XPATH,
            "//div[@jsname='DOFKe' or @data-meeting-title or @aria-label='Meeting controls']"
        )
        if toolbar.is_displayed():
            print("[BOT] ✅ Admission signal: meeting controls toolbar found")
            return True
    except NoSuchElementException:
        pass

    # Signal 4: Look for the mute/unmute button by icon or tooltip
    mute_labels = ["Turn off microphone", "Turn on microphone", "Mute", "Unmute"]
    for label in mute_labels:
        try:
            btn = driver.find_element(By.XPATH, f"//button[@aria-label='{label}']")
            if btn.is_displayed():
                print(f"[BOT] ✅ Admission signal: found mute button '{label}'")
                return True
        except NoSuchElementException:
            pass

    # Signal 5: Page title changes from "Waiting..." to the meeting name
    try:
        title = driver.title.lower()
        if "waiting" not in title and "ask to join" not in title and "meet" in title:
            print(f"[BOT] ✅ Admission signal: page title changed to '{driver.title}'")
            return True
    except Exception:
        pass

    return False


def _is_meeting_ended(driver) -> tuple[bool, str]:
    """
    Multi-signal check for whether the meeting has ended or the bot was kicked.
    Returns (True, reason_string) or (False, "").
    """
    try:
        current_url = driver.current_url
    except WebDriverException:
        return True, "Browser/driver crashed"

    # Signal 1: URL left Google Meet entirely
    if "meet.google.com" not in current_url:
        return True, f"URL left Meet: {current_url}"

    # Signal 2: Google Meet's post-call screen URL
    if "/left" in current_url or "lookup" in current_url:
        return True, f"Post-call URL detected: {current_url}"

    # Signal 3: Check page source for end-of-meeting strings
    # Use a JS snippet — faster than fetching the whole page_source
    try:
        end_strings = [
            "you've been removed",
            "you have been removed",
            "the meeting has ended",
            "return to home screen",
            "left the meeting",
            "meeting ended",
            "kicked from",
        ]
        # Pull innerText of body — faster and catches React-rendered text
        body_text = driver.execute_script(
            "return document.body ? document.body.innerText.toLowerCase() : '';"
        )
        for s in end_strings:
            if s in body_text:
                return True, f"End text detected: '{s}'"
    except WebDriverException:
        return True, "JS execution failed — browser likely crashed"

    # Signal 4: Leave button has disappeared (you were kicked or meeting ended)
    leave_found = False
    for label in ["Leave call", "Leave meeting", "End call", "Hang up"]:
        try:
            btn = driver.find_element(By.XPATH, f"//button[@aria-label='{label}']")
            if btn.is_displayed():
                leave_found = True
                break
        except NoSuchElementException:
            pass

    if not leave_found:
        # Don't trigger immediately — do a double-check after a short pause
        # to avoid false positives during UI transitions
        return True, "Leave button disappeared"

    return False, ""


def _start_ffmpeg(output_path: str) -> subprocess.Popen:
    """Start FFmpeg recording from PulseAudio default sink monitor."""
    print(f"[BOT] 🎙️  Starting FFmpeg → {output_path}")
    cmd = [
        "ffmpeg",
        "-f", "pulse",
        "-i", "default",          # PulseAudio default source (microphone or monitor)
        "-acodec", "pcm_s16le",   # 16-bit PCM — required by most speech APIs
        "-ar", "16000",           # 16 kHz sample rate
        "-ac", "1",               # Mono
        "-y",                     # Overwrite without asking
        output_path,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,    # Capture stderr so you can debug FFmpeg issues
    )
    # Give FFmpeg a moment to start and validate it didn't immediately crash
    time.sleep(2)
    if proc.poll() is not None:
        stderr_output = proc.stderr.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg failed to start:\n{stderr_output}")
    print("[BOT] ✅ FFmpeg recording started")
    return proc


def _stop_ffmpeg(proc: subprocess.Popen, temp_path: str, final_path: str) -> bool:
    """
    Gracefully stop FFmpeg and finalize the audio file.
    Returns True if the final file exists and has content.
    """
    if proc is None:
        return False

    # Send SIGTERM — FFmpeg catches this and writes its file trailer cleanly
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        print("[BOT] ⚠️  FFmpeg didn't stop gracefully, killing...")
        proc.kill()
        proc.wait()

    if os.path.exists(temp_path):
        size = os.path.getsize(temp_path)
        if size > 0:
            os.rename(temp_path, final_path)
            print(f"[BOT] ✅ Audio saved: {final_path} ({size / 1024:.1f} KB)")
            return True
        else:
            print(f"[BOT] ⚠️  Audio file is empty: {temp_path}")
            os.remove(temp_path)
            return False
    else:
        print(f"[BOT] ⚠️  Temp audio file not found: {temp_path}")
        return False


def _run_bot_sync(meet_url: str, bot_name: str = "AI Scribe Bot") -> str | None:
    """
    Main synchronous bot logic.
    Returns the path to the recorded audio file, or None on failure.
    """
    os.environ["DISPLAY"] = ":99"  # Xvfb virtual display

    timestamp = int(time.time())
    temp_audio = f"meeting_audio_{timestamp}_temp.wav"
    final_audio = f"meeting_audio_{timestamp}.wav"
    ffmpeg_proc = None
    driver = None

    print(f"[BOT] ══════════════════════════════════════════")
    print(f"[BOT] Meet URL : {meet_url}")
    print(f"[BOT] Bot Name : {bot_name}")
    print(f"[BOT] ══════════════════════════════════════════")

    try:
        # ── STEP 1: Launch Chrome ──────────────────────────────────────────────
        print("[BOT] Launching Chrome...")
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        # These two flags grant mic/camera without a popup dialog
        options.add_argument("--use-fake-ui-for-media-stream")
        # Remove --use-fake-device-for-media-stream so PulseAudio is used for real audio
        options.add_argument("--lang=en-US")
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 1,
        })

        # Auto-detect installed Chrome version
        chrome_binary = "/usr/bin/google-chrome"
        chrome_version = None
        if os.path.exists(chrome_binary):
            try:
                ver_str = subprocess.check_output(
                    [chrome_binary, "--version"]
                ).decode().strip()
                chrome_version = int(ver_str.split()[-1].split(".")[0])
                print(f"[BOT] Chrome version: {chrome_version}")
            except Exception as e:
                print(f"[BOT] Could not detect Chrome version: {e}")
                chrome_binary = None
        else:
            chrome_binary = None

        driver = uc.Chrome(
            options=options,
            use_subprocess=True,
            browser_executable_path=chrome_binary,
            version_main=chrome_version,
        )
        driver.implicitly_wait(5)  # Short implicit wait; we do explicit waits below
        print("[BOT] ✅ Chrome launched")

        # ── STEP 2: Navigate to Meet ───────────────────────────────────────────
        print("[BOT] Navigating to meeting URL...")
        driver.get(meet_url)
        time.sleep(5)  # Let the page fully load JS
        _save_screenshot(driver, "01_after_navigation")

        # ── STEP 3: Enter name (pre-join lobby) ───────────────────────────────
        print("[BOT] Looking for name input field...")
        try:
            name_input = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    "//input[@placeholder='Your name' or @aria-label='Your name']"
                ))
            )
            name_input.clear()
            name_input.send_keys(bot_name)
            print(f"[BOT] ✅ Name entered: {bot_name}")
            time.sleep(1)
        except TimeoutException:
            print("[BOT] No name field found — may already be signed in. Continuing...")
        _save_screenshot(driver, "02_after_name_entry")

        # ── STEP 4: Dismiss mic/camera toggles (turn both off) ────────────────
        # This prevents the bot from broadcasting noise into the meeting
        print("[BOT] Turning off mic and camera...")
        for aria in ["Turn off microphone", "Turn on microphone",
                     "Turn off camera", "Turn on camera"]:
            try:
                btn = driver.find_element(By.XPATH, f"//button[@aria-label='{aria}']")
                if "off" not in aria.lower() and btn.is_displayed():
                    btn.click()
                    time.sleep(0.5)
            except NoSuchElementException:
                pass

        # ── STEP 5: Click "Ask to join" / "Join now" ──────────────────────────
        print("[BOT] Clicking join button...")
        join_xpaths = [
            "//button[contains(., 'Ask to join')]",
            "//button[contains(., 'Join now')]",
            "//button[contains(., 'Join')]",
            "//span[contains(., 'Ask to join')]/ancestor::button",
            "//span[contains(., 'Join now')]/ancestor::button",
        ]
        clicked = False
        for xpath in join_xpaths:
            try:
                btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                btn.click()
                print(f"[BOT] ✅ Clicked join button (xpath: {xpath})")
                clicked = True
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if not clicked:
            _save_screenshot(driver, "03_join_button_not_found")
            raise RuntimeError("Could not find or click the join button.")

        _save_screenshot(driver, "03_after_join_click")

        # ── STEP 6: Start recording AFTER joining lobby ────────────────────────
        # Recording from lobby is fine — the important thing is FFmpeg is running
        # before we get admitted so we don't miss the first seconds of meeting audio
        ffmpeg_proc = _start_ffmpeg(temp_audio)

        # ── STEP 7: Wait for admission ─────────────────────────────────────────
        print(f"[BOT] ⏳ Waiting up to {ADMISSION_TIMEOUT}s to be admitted...")
        admitted = False
        screenshot_interval = 15  # Save a screenshot every N seconds while waiting
        last_screenshot_time = time.time()

        for attempt in range(ADMISSION_TIMEOUT // 2):
            time.sleep(2)

            # Periodic screenshots to debug lobby state
            if time.time() - last_screenshot_time >= screenshot_interval:
                _save_screenshot(driver, f"lobby_{attempt:03d}")
                last_screenshot_time = time.time()

            if "meet.google.com" not in driver.current_url:
                print("[BOT] 🛑 Redirected away from Meet while waiting. Aborting.")
                break

            if _is_admitted(driver):
                admitted = True
                break

        if not admitted:
            _save_screenshot(driver, "04_admission_failed")
            print("[BOT] ❌ Was not admitted within the timeout. Stopping.")
            _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)
            ffmpeg_proc = None  # Mark as already handled
            return None

        _save_screenshot(driver, "04_admitted_to_meeting")
        print("[BOT] 🎉 Inside the meeting! Monitoring for end...")

        # ── STEP 8: Monitor meeting until it ends ─────────────────────────────
        start_time = time.time()
        consecutive_end_signals = 0  # Require 2 consecutive signals to avoid false positives

        while True:
            time.sleep(3)

            elapsed = time.time() - start_time
            if elapsed >= MAX_MEETING_DURATION:
                print(f"[BOT] 🛑 Hard timeout ({MAX_MEETING_DURATION}s). Exiting.")
                break

            ended, reason = _is_meeting_ended(driver)
            if ended:
                consecutive_end_signals += 1
                print(f"[BOT] ⚠️  End signal ({consecutive_end_signals}/2): {reason}")
                if consecutive_end_signals >= 2:
                    print(f"[BOT] 🛑 Meeting ended confirmed: {reason}")
                    break
                time.sleep(3)  # Wait before second check
            else:
                consecutive_end_signals = 0  # Reset on a clean check

        _save_screenshot(driver, "05_after_meeting_end")

        # ── STEP 9: Stop recording and return file path ────────────────────────
        success = _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)
        ffmpeg_proc = None  # Mark as handled so finally block skips it

        if success:
            print(f"[BOT] ✅ Audio ready for transcription: {final_audio}")
            return final_audio
        else:
            print("[BOT] ❌ Audio file missing or empty. Nothing to transcribe.")
            return None

    except Exception as e:
        print(f"[BOT] ❌ Fatal error: {e}")
        if driver:
            _save_screenshot(driver, "fatal_error")
        raise

    finally:
        # Only stop FFmpeg here if it wasn't already stopped above
        if ffmpeg_proc is not None:
            print("[BOT] [finally] Stopping FFmpeg...")
            _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)

        if driver:
            print("[BOT] [finally] Closing browser...")
            try:
                driver.quit()
            except Exception:
                pass


# ── Async wrapper for FastAPI ──────────────────────────────────────────────────
async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot") -> str | None:
    """Run the bot in a thread so it doesn't block the FastAPI event loop."""
    return await asyncio.to_thread(_run_bot_sync, meet_url, bot_name)


# ── Local test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    test_url = input("Paste a Google Meet link to test: ").strip()
    result = asyncio.run(join_meet_and_record(test_url))
    if result:
        print(f"\n✅ Recording complete: {result}")
    else:
        print("\n❌ Bot finished without producing an audio file.")