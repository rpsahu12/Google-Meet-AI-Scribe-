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
from urllib3.exceptions import MaxRetryError, NewConnectionError

# --- CONFIGURATION ---
DEBUG_DIR            = "debug_screenshots"
MAX_MEETING_DURATION = 7200   # 2 hour hard cap
ADMISSION_TIMEOUT    = 120    # seconds to wait for host to admit bot
MONITOR_INTERVAL     = 3      # seconds between in-meeting checks
MAX_DRIVER_ERRORS    = 5      # consecutive driver errors before giving up


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_screenshot(driver, name):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, f"{name}.png")
        driver.save_screenshot(filepath)
        print(f"[BOT] 📸 Screenshot: {filepath}")
    except Exception as e:
        print(f"[BOT] Screenshot failed ({name}): {e}")


def _safe_driver_call(fn, default=None):
    """
    Wrap any Selenium call so a ChromeDriver crash/disconnect
    returns `default` instead of killing the whole bot.
    """
    try:
        return fn()
    except (
        WebDriverException,
        MaxRetryError,
        NewConnectionError,
        ConnectionResetError,
        ConnectionRefusedError,
        OSError,
    ) as e:
        msg = str(e)
        if "cannot determine loading status" not in msg and \
           "target window already closed" not in msg:
            print(f"[BOT] ⚠️  Driver call failed (non-fatal): {msg[:120]}")
        return default


def _get_page_text(driver) -> str:
    result = _safe_driver_call(
        lambda: driver.execute_script(
            "return document.body ? document.body.innerText.toLowerCase() : '';"
        ),
        default=""
    )
    return result or ""


def _get_current_url(driver) -> str:
    return _safe_driver_call(lambda: driver.current_url, default="")


def _find_element_safe(driver, xpath):
    try:
        el = driver.find_element(By.XPATH, xpath)
        return el if el.is_displayed() else None
    except Exception:
        return None


# ── Admission detection ───────────────────────────────────────────────────────

def _is_admitted(driver) -> bool:
    """5 independent signals — any one firing = bot is inside the meeting."""

    # Signal 1: Leave/End call button
    for label in ["Leave call", "Leave meeting", "End call", "Hang up"]:
        if _find_element_safe(driver, f"//button[@aria-label='{label}']"):
            print(f"[BOT] ✅ Admitted — leave button: '{label}'")
            return True

    # Signal 2: Participant tile (only rendered inside the meeting)
    if _find_element_safe(driver, "//*[@data-participant-id]"):
        print("[BOT] ✅ Admitted — participant tile found")
        return True

    # Signal 3: Mute/unmute button in the in-meeting toolbar
    for label in ["Turn off microphone", "Turn on microphone", "Mute", "Unmute"]:
        if _find_element_safe(driver, f"//button[@aria-label='{label}']"):
            print(f"[BOT] ✅ Admitted — mute button: '{label}'")
            return True

    # Signal 4: Meeting controls toolbar container
    for attr in ["jsname='DOFKe'", "data-meeting-title", "aria-label='Meeting controls'"]:
        if _find_element_safe(driver, f"//*[@{attr}]"):
            print(f"[BOT] ✅ Admitted — controls toolbar: @{attr}")
            return True

    # Signal 5: Page title no longer says "Waiting" / "Ask to join"
    title = _safe_driver_call(lambda: driver.title.lower(), default="")
    if title and "waiting" not in title and "ask to join" not in title and "meet" in title:
        print(f"[BOT] ✅ Admitted — page title: '{title}'")
        return True

    # Signal 6: Rendered page text shows in-meeting UI
    body = _get_page_text(driver)
    if body and ("contributors" in body or "in the meeting" in body):
        url = _get_current_url(driver)
        if url and "/lookup" not in url:
            print("[BOT] ✅ Admitted — 'in the meeting' text found")
            return True

    return False


# ── Meeting-end detection ─────────────────────────────────────────────────────

def _is_meeting_ended(driver) -> tuple[bool, str]:
    url = _get_current_url(driver)

    if url is None:
        return True, "Driver unreachable — Chrome likely crashed"
    if "meet.google.com" not in url:
        return True, f"URL left Meet: {url}"
    if "/left" in url:
        return True, f"Post-call URL: {url}"

    body = _get_page_text(driver)
    if body is None:
        return True, "Could not read page — browser likely crashed"

    for phrase in [
        "you've been removed", "you have been removed",
        "the meeting has ended", "return to home screen",
        "meeting ended", "left the meeting", "this meeting has ended",
    ]:
        if phrase in body:
            return True, f"End phrase: '{phrase}'"

    leave_visible = any(
        _find_element_safe(driver, f"//button[@aria-label='{label}']")
        for label in ["Leave call", "Leave meeting", "End call", "Hang up"]
    )
    if not leave_visible:
        return True, "Leave button not found"

    return False, ""


# ── FFmpeg helpers ────────────────────────────────────────────────────────────

def _start_ffmpeg(output_path: str) -> subprocess.Popen:
    print(f"[BOT] 🎙️  Starting FFmpeg → {output_path}")
    cmd = [
        "ffmpeg", "-f", "pulse", "-i", "default",
        "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        "-y", output_path,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    time.sleep(2)
    if proc.poll() is not None:
        err = proc.stderr.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"FFmpeg failed to start:\n{err}")
    print("[BOT] ✅ FFmpeg recording started")
    return proc


def _stop_ffmpeg(proc, temp_path: str, final_path: str) -> bool:
    if proc is None:
        return False
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
        os.rename(temp_path, final_path)
        print(f"[BOT] ✅ Audio saved: {final_path} ({os.path.getsize(final_path)/1024:.1f} KB)")
        return True
    print(f"[BOT] ⚠️  Audio file missing or empty: {temp_path}")
    return False


# ── Main bot logic ────────────────────────────────────────────────────────────

def _run_bot_sync(meet_url: str, bot_name: str = "AI Scribe Bot") -> str | None:
    os.environ["DISPLAY"] = ":99"

    timestamp   = int(time.time())
    temp_audio  = f"meeting_audio_{timestamp}_temp.wav"
    final_audio = f"meeting_audio_{timestamp}.wav"
    ffmpeg_proc = None
    driver      = None

    print(f"[BOT] ══════════════════════════════════════════")
    print(f"[BOT] Meet URL : {meet_url}")
    print(f"[BOT] Bot Name : {bot_name}")
    print(f"[BOT] ══════════════════════════════════════════")

    try:
        # ── STEP 1: Launch Chrome ──────────────────────────────────────────
        print("[BOT] Launching Chrome...")
        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--use-fake-ui-for-media-stream")
        # ❌ NOT --use-fake-device-for-media-stream (that silences real audio)
        options.add_argument("--lang=en-US")
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 1,
        })

        chrome_binary  = "/usr/bin/google-chrome"
        chrome_version = None
        if os.path.exists(chrome_binary):
            try:
                ver = subprocess.check_output([chrome_binary, "--version"]).decode().strip()
                chrome_version = int(ver.split()[-1].split(".")[0])
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
        driver.implicitly_wait(5)
        print("[BOT] ✅ Chrome launched")

        # ── STEP 2: Navigate ───────────────────────────────────────────────
        print("[BOT] Navigating to meeting URL...")
        driver.get(meet_url)
        time.sleep(5)
        _save_screenshot(driver, "01_after_navigation")

        # ── STEP 3: Enter name ─────────────────────────────────────────────
        print("[BOT] Looking for name input...")
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
            print("[BOT] No name field — may already be signed in. Continuing...")
        _save_screenshot(driver, "02_after_name_entry")

        # ── STEP 4: Click join button ──────────────────────────────────────
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
                print(f"[BOT] ✅ Clicked join button")
                clicked = True
                break
            except (TimeoutException, NoSuchElementException):
                continue

        if not clicked:
            _save_screenshot(driver, "03_join_button_not_found")
            raise RuntimeError("Could not find or click the join button.")

        _save_screenshot(driver, "03_after_join_click")

        # ── STEP 5: Start recording from lobby ────────────────────────────
        ffmpeg_proc = _start_ffmpeg(temp_audio)

        # ── STEP 6: Wait for admission ─────────────────────────────────────
        print(f"[BOT] ⏳ Waiting up to {ADMISSION_TIMEOUT}s to be admitted...")
        admitted           = False
        last_screenshot_t  = time.time()
        driver_error_count = 0

        for attempt in range(ADMISSION_TIMEOUT // 2):
            time.sleep(2)

            if time.time() - last_screenshot_t >= 15:
                _save_screenshot(driver, f"lobby_{attempt:03d}")
                last_screenshot_t = time.time()

            url = _get_current_url(driver)
            if url is None:
                driver_error_count += 1
                print(f"[BOT] ⚠️  Driver unreachable in lobby ({driver_error_count}/{MAX_DRIVER_ERRORS})")
                if driver_error_count >= MAX_DRIVER_ERRORS:
                    print("[BOT] 🛑 Too many driver errors. Aborting.")
                    break
                continue

            driver_error_count = 0

            if "meet.google.com" not in url:
                print("[BOT] 🛑 Redirected away from Meet. Aborting.")
                break

            if _is_admitted(driver):
                admitted = True
                break

        if not admitted:
            _save_screenshot(driver, "04_admission_failed")
            print("[BOT] ❌ Not admitted within timeout.")
            _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)
            ffmpeg_proc = None
            return None

        _save_screenshot(driver, "04_admitted_to_meeting")
        print("[BOT] 🎉 Inside the meeting! Monitoring for end...")

        # ── STEP 7: Monitor until meeting ends ────────────────────────────
        start_time              = time.time()
        consecutive_end_signals = 0
        driver_error_count      = 0

        while True:
            time.sleep(MONITOR_INTERVAL)

            if time.time() - start_time >= MAX_MEETING_DURATION:
                print(f"[BOT] 🛑 Hard timeout reached. Exiting.")
                break

            ended, reason = _is_meeting_ended(driver)

            if ended:
                url = _get_current_url(driver)
                if url is None:
                    # Driver crash — count separately
                    driver_error_count += 1
                    print(f"[BOT] ⚠️  Driver unreachable ({driver_error_count}/{MAX_DRIVER_ERRORS}): {reason}")
                    if driver_error_count >= MAX_DRIVER_ERRORS:
                        print("[BOT] 🛑 Driver crashed. Stopping.")
                        break
                    continue

                consecutive_end_signals += 1
                print(f"[BOT] ⚠️  End signal {consecutive_end_signals}/2: {reason}")
                if consecutive_end_signals >= 2:
                    print(f"[BOT] 🛑 Meeting ended: {reason}")
                    break
                time.sleep(3)
            else:
                consecutive_end_signals = 0
                driver_error_count      = 0

        _save_screenshot(driver, "05_after_meeting_end")

        # ── STEP 8: Stop recording ─────────────────────────────────────────
        success     = _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)
        ffmpeg_proc = None  # Prevent finally from double-stopping

        if success:
            print(f"[BOT] ✅ Ready for transcription: {final_audio}")
            return final_audio
        else:
            print("[BOT] ❌ Audio missing or empty.")
            return None

    except Exception as e:
        print(f"[BOT] ❌ Fatal error: {e}")
        if driver:
            _save_screenshot(driver, "fatal_error")
        raise

    finally:
        if ffmpeg_proc is not None:
            print("[BOT] [finally] Stopping FFmpeg...")
            _stop_ffmpeg(ffmpeg_proc, temp_audio, final_audio)
        if driver:
            print("[BOT] [finally] Closing browser...")
            try:
                driver.quit()
            except Exception:
                pass


# ── Async wrapper for FastAPI ─────────────────────────────────────────────────

async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot") -> str | None:
    return await asyncio.to_thread(_run_bot_sync, meet_url, bot_name)


# ── Local test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_url = input("Paste a Google Meet link to test: ").strip()
    result   = asyncio.run(join_meet_and_record(test_url))
    print(f"\n{'✅ Recording: ' + result if result else '❌ No audio file produced.'}")