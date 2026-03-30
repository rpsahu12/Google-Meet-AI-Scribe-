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
    """Save a debug screenshot for troubleshooting on EC2."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, f"{name}.png")
        driver.save_screenshot(filepath)
        print(f"[BOT] 📸 Screenshot: {filepath}")
    except Exception as e:
        print(f"[BOT] Screenshot failed ({name}): {e}")


def _run_bot_sync(meet_url: str, bot_name: str = "AI Scribe Bot"):
    """
    Synchronous bot function that uses Selenium + undetected-chromedriver.
    Based on the proven Google-Meet-Bot approach (Selenium + Chrome).
    Designed for AWS EC2 with Xvfb virtual display.
    """
    audio_filename = f"meeting_audio_{int(time.time())}.wav"
    temp_audio_filename = f"meeting_audio_{int(time.time())}_temp.wav"
    ffmpeg_process = None
    driver = None

    print(f"[BOT] ═══════════════════════════════════════")
    print(f"[BOT] Starting bot for: {meet_url}")
    print(f"[BOT] Bot name: {bot_name}")
    print(f"[BOT] ═══════════════════════════════════════")

    try:
        # === STEP 1: Launch Chrome with undetected-chromedriver ===
        print("[BOT] Step 1: Launching Chrome...")

        options = uc.ChromeOptions()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")

        # Auto-grant camera/mic permissions (critical for Google Meet)
        options.add_experimental_option("prefs", {
            "profile.default_content_setting_values.media_stream_mic": 1,
            "profile.default_content_setting_values.media_stream_camera": 1,
            "profile.default_content_setting_values.geolocation": 0,
            "profile.default_content_setting_values.notifications": 1,
        })

        # Use fake media streams (no real camera/mic needed on EC2)
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--use-fake-device-for-media-stream")

        # Auto-detect Chrome binary location on EC2/Ubuntu
        chrome_paths = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
        chrome_binary = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_binary = path
                break

        if chrome_binary:
            print(f"[BOT] Chrome binary found: {chrome_binary}")
            options.binary_location = chrome_binary

        # Auto-detect Chrome version to match ChromeDriver
        chrome_version = None
        if chrome_binary:
            try:
                import subprocess as sp
                version_output = sp.check_output([chrome_binary, "--version"]).decode().strip()
                # Output like: "Google Chrome 146.0.7680.164"
                chrome_version = int(version_output.split()[-1].split(".")[0])
                print(f"[BOT] Chrome version detected: {chrome_version}")
            except Exception:
                pass

        driver = uc.Chrome(
            options=options,
            browser_executable_path=chrome_binary,
            version_main=chrome_version,
        )
        driver.implicitly_wait(5)
        print("[BOT] ✅ Chrome launched")

        # === STEP 2: Navigate to Google Meet ===
        print("[BOT] Step 2: Navigating to meeting...")
        driver.get(meet_url)
        time.sleep(3)

        current_url = driver.current_url
        print(f"[BOT] Page loaded — URL: {current_url}")
        _save_screenshot(driver, "01_page_loaded")

        # Check for redirect (invalid link)
        if "meet.google.com" not in current_url:
            raise Exception(f"Redirected away from Meet → {current_url}")

        # === STEP 3: Dismiss any dialogs / overlays ===
        print("[BOT] Step 3: Handling dialogs...")
        _dismiss_dialogs(driver)

        # === STEP 4: Enter bot name (guest flow) ===
        print("[BOT] Step 4: Entering bot name...")
        _enter_name(driver, bot_name)
        time.sleep(1)

        # === STEP 5: Turn off mic and camera ===
        print("[BOT] Step 5: Turning off mic and camera...")
        _turn_off_mic_cam(driver)
        _save_screenshot(driver, "02_before_join")

        # === STEP 6: Click "Ask to Join" ===
        print("[BOT] Step 6: Clicking 'Ask to Join'...")
        time.sleep(2)
        _click_join(driver)
        _save_screenshot(driver, "03_join_clicked")

        # === STEP 7: Wait for admission ===
        print("[BOT] Step 7: Waiting to be admitted (120s timeout)...")
        print("[BOT] ⏳ Please admit the bot from the host account!")
        _wait_for_admission(driver, timeout=120)
        print("[BOT] ✅ Admitted to the meeting!")
        _save_screenshot(driver, "04_in_meeting")

        # === STEP 8: Start audio recording ===
        print("[BOT] 🎙️ Starting FFmpeg audio capture...")
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "pulse",
            "-i", "default",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            temp_audio_filename,
            "-y",
        ]
        ffmpeg_process = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # === STEP 9: Monitor meeting until it ends ===
        print("[BOT] 📍 Monitoring meeting — recording until it ends...")
        _wait_for_meeting_end(driver)
        print("[BOT] Meeting ended. Stopping recording...")

        # Stop FFmpeg
        if ffmpeg_process:
            ffmpeg_process.terminate()
            ffmpeg_process.wait()

        # Finalize audio file
        if os.path.exists(temp_audio_filename):
            os.rename(temp_audio_filename, audio_filename)
            print(f"[BOT] ✅ Audio saved to {audio_filename}")
            return audio_filename
        else:
            print("[BOT] ❌ Failed to save audio file")
            return None

    except Exception as e:
        print(f"[BOT] ❌ Fatal error: {e}")
        if driver:
            _save_screenshot(driver, "error_final")
        # Salvage partial audio
        if os.path.exists(temp_audio_filename):
            os.rename(temp_audio_filename, audio_filename)
            print(f"[BOT] ⚠️ Partial audio saved to {audio_filename}")
        return None

    finally:
        # Cleanup FFmpeg
        if ffmpeg_process and ffmpeg_process.poll() is None:
            ffmpeg_process.terminate()
            try:
                ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                ffmpeg_process.kill()

        # Cleanup browser
        if driver:
            try:
                driver.quit()
                print("[BOT] Browser closed")
            except Exception:
                pass


# ============================================================
#  HELPER FUNCTIONS
# ============================================================

def _dismiss_dialogs(driver):
    """Dismiss cookie consent, 'Got it', and other overlay dialogs."""
    dismiss_texts = [
        "Got it", "Dismiss", "Accept all", "Accept",
        "Continue without signing in", "Skip", "OK", "Close",
    ]
    for text in dismiss_texts:
        try:
            buttons = driver.find_elements(By.XPATH, f'//button[contains(text(), "{text}")]')
            for btn in buttons:
                if btn.is_displayed():
                    btn.click()
                    print(f"[BOT] 🗑️ Dismissed: {text}")
                    time.sleep(0.5)
        except Exception:
            pass


def _enter_name(driver, bot_name):
    """Enter the bot name in the guest name field."""
    name_selectors = [
        (By.CSS_SELECTOR, 'input[aria-label="Your name"]'),
        (By.CSS_SELECTOR, 'input[placeholder="Your name"]'),
        (By.CSS_SELECTOR, 'input[type="text"][jsname="YPqjbf"]'),
    ]

    for by, selector in name_selectors:
        try:
            name_input = driver.find_element(by, selector)
            if name_input.is_displayed():
                name_input.clear()
                name_input.send_keys(bot_name)
                print(f"[BOT] ✏️ Name entered: {bot_name}")
                return True
        except (NoSuchElementException, Exception):
            pass

    print("[BOT] ℹ️ No name input found (may already be logged in)")
    return False


def _turn_off_mic_cam(driver):
    """Turn off microphone and camera in the Meet lobby."""

    # --- Mic toggle ---
    mic_selectors = [
        # Reference repo's selector (jscontroller-based)
        (By.CSS_SELECTOR, 'div[jscontroller="t2mBxb"][data-anchor-id="hw0c9"]'),
        # aria-label based
        (By.CSS_SELECTOR, 'button[aria-label*="Turn off microphone"]'),
        (By.CSS_SELECTOR, '[aria-label*="Turn off microphone"]'),
        (By.CSS_SELECTOR, 'button[data-is-muted="false"][aria-label*="microphone" i]'),
    ]

    for by, selector in mic_selectors:
        try:
            el = driver.find_element(by, selector)
            if el.is_displayed():
                el.click()
                print("[BOT] 🎤 Microphone turned off")
                time.sleep(0.5)
                break
        except (NoSuchElementException, Exception):
            pass

    # --- Camera toggle ---
    cam_selectors = [
        # Reference repo's selector
        (By.CSS_SELECTOR, 'div[jscontroller="bwqwSd"][data-anchor-id="psRWwc"]'),
        # aria-label based
        (By.CSS_SELECTOR, 'button[aria-label*="Turn off camera"]'),
        (By.CSS_SELECTOR, '[aria-label*="Turn off camera"]'),
        (By.CSS_SELECTOR, 'button[data-is-muted="false"][aria-label*="camera" i]'),
    ]

    for by, selector in cam_selectors:
        try:
            el = driver.find_element(by, selector)
            if el.is_displayed():
                el.click()
                print("[BOT] 📷 Camera turned off")
                time.sleep(0.5)
                break
        except (NoSuchElementException, Exception):
            pass


def _click_join(driver):
    """Click the 'Ask to Join' or 'Join now' button. Multiple strategies with retry."""

    join_selectors = [
        # Strategy 1: The exact jsname selector from the reference repo (proven to work)
        (By.CSS_SELECTOR, 'button[jsname="Qx7uuf"]'),
        # Strategy 2: aria-label based
        (By.CSS_SELECTOR, 'button[aria-label*="Ask to join"]'),
        (By.CSS_SELECTOR, 'button[aria-label*="Join now"]'),
        # Strategy 3: Text-based via XPath
        (By.XPATH, '//button[contains(text(), "Ask to join")]'),
        (By.XPATH, '//button[contains(text(), "Join now")]'),
        # Strategy 4: Span inside button (Google often wraps text in spans)
        (By.XPATH, '//button[.//span[contains(text(), "Ask to join")]]'),
        (By.XPATH, '//button[.//span[contains(text(), "Join now")]]'),
    ]

    for attempt in range(3):
        for by, selector in join_selectors:
            try:
                btn = driver.find_element(by, selector)
                if btn.is_displayed() and btn.is_enabled():
                    btn.click()
                    print(f"[BOT] ✅ Clicked join button: {selector}")
                    return True
            except (NoSuchElementException, Exception):
                pass

        if attempt < 2:
            print(f"[BOT] Join attempt {attempt + 1} failed, retrying in 3s...")
            _save_screenshot(driver, f"join_attempt_{attempt + 1}_failed")
            _dismiss_dialogs(driver)
            time.sleep(3)

    # Final fallback: JavaScript click on any visible join-like button
    try:
        result = driver.execute_script("""
            const buttons = Array.from(document.querySelectorAll('button'));
            for (const btn of buttons) {
                const text = (btn.textContent || '').toLowerCase().trim();
                if ((text.includes('ask to join') || text.includes('join now')) && btn.offsetParent !== null) {
                    btn.click();
                    return text;
                }
            }
            return null;
        """)
        if result:
            print(f"[BOT] ✅ Clicked join button via JS fallback: '{result}'")
            return True
    except Exception:
        pass

    _save_screenshot(driver, "join_FAILED_final")
    raise Exception("Failed to click 'Ask to join' after all attempts")


def _wait_for_admission(driver, timeout=120):
    """Wait until the bot is admitted into the meeting."""
    try:
        # Wait for any element that only exists inside an active meeting
        WebDriverWait(driver, timeout).until(
            lambda d: _is_in_meeting(d)
        )
    except TimeoutException:
        _save_screenshot(driver, "admission_timeout")
        raise Exception(f"Bot was not admitted within {timeout} seconds")


def _is_in_meeting(driver):
    """Check if the bot is inside an active meeting (past the lobby)."""
    # Look for elements that only appear once you're IN the meeting
    meeting_indicators = [
        'button[aria-label*="Leave call"]',
        'button[aria-label*="Show everyone"]',
        'button[aria-label*="Turn on microphone"]',
        'button[aria-label*="Turn off microphone"]',
        '[data-call-ended="false"]',
        'button[aria-label*="Present now"]',
    ]

    for selector in meeting_indicators:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for el in elements:
                if el.is_displayed():
                    return True
        except Exception:
            pass

    # Also check via JavaScript
    try:
        result = driver.execute_script("""
            const buttons = Array.from(document.querySelectorAll('button'));
            return buttons.some(b => {
                const label = (b.getAttribute('aria-label') || '').toLowerCase();
                return label.includes('leave call') || label.includes('show everyone');
            });
        """)
        return bool(result)
    except Exception:
        return False


def _wait_for_meeting_end(driver):
    """Monitor the meeting and wait until it ends."""
    while True:
        time.sleep(5)

        # Check for meeting-ended indicators
        end_indicators = [
            '//div[contains(text(), "The meeting has ended")]',
            '//div[contains(text(), "You have been disconnected")]',
            '//div[contains(text(), "Meeting ended")]',
            '//button[contains(text(), "Rejoin")]',
            '//button[contains(text(), "Return to home screen")]',
        ]

        for xpath in end_indicators:
            try:
                elements = driver.find_elements(By.XPATH, xpath)
                for el in elements:
                    if el.is_displayed():
                        print(f"[BOT] 🔔 Meeting ended: {xpath}")
                        return
            except Exception:
                pass

        # Fallback: check if meeting controls disappeared
        try:
            leave_buttons = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label*="Leave call"]')
            mic_buttons = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label*="microphone"]')
            visible_controls = any(
                el.is_displayed() for el in leave_buttons + mic_buttons
            )
            if not visible_controls:
                # Double-check - maybe we got disconnected
                time.sleep(3)
                leave_buttons2 = driver.find_elements(By.CSS_SELECTOR, 'button[aria-label*="Leave call"]')
                if not any(el.is_displayed() for el in leave_buttons2):
                    print("[BOT] 🔔 Meeting controls gone — meeting likely ended")
                    return
        except Exception as e:
            print(f"[BOT] Page error — assuming meeting ended: {e}")
            return


# ============================================================
#  ASYNC WRAPPER (for compatibility with FastAPI's async app.py)
# ============================================================

async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot"):
    """
    Async wrapper around the synchronous Selenium bot.
    Runs the blocking Selenium code in a thread pool so FastAPI stays responsive.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_bot_sync, meet_url, bot_name)
    return result


# --- Test Execution ---
if __name__ == "__main__":
    test_url = input("Paste a Google Meet link to test: ")
    result = _run_bot_sync(test_url)
    if result:
        print(f"\n✅ Recording saved: {result}")
    else:
        print("\n❌ Bot failed")