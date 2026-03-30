import asyncio
import subprocess
import os
import time
import random
import re
from playwright.async_api import async_playwright

# Graceful import — bot will still function without stealth, but may get blocked
try:
    from playwright_stealth import stealth_async
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False
    print("[BOT] ⚠️  playwright-stealth not installed. Run: pip install playwright-stealth")


# --- CONFIGURATION ---
DEBUG_DIR = "debug_screenshots"
BOT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Comprehensive anti-detection JavaScript injected into every page
STEALTH_INIT_SCRIPT = """
    // 1. Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. Fake chrome runtime (critical — Google services check this)
    if (!window.chrome) {
        window.chrome = {};
    }
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
        onMessage: { addListener: function() {}, removeListener: function() {} },
        id: undefined
    };
    window.chrome.loadTimes = function() { return {}; };
    window.chrome.csi = function() { return {}; };

    // 3. Realistic navigator.plugins (Chrome always has these 3)
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const makePlugin = (name, filename, desc) => {
                const p = { name, filename, description: desc, length: 1 };
                p[0] = { type: 'application/pdf', suffixes: 'pdf', description: '', enabledPlugin: p };
                return p;
            };
            const plugins = [
                makePlugin('Chrome PDF Plugin', 'internal-pdf-viewer', 'Portable Document Format'),
                makePlugin('Chrome PDF Viewer', 'mhjfbmdgcfjbbpaeojofohoefgiehjai', ''),
                makePlugin('Native Client', 'internal-nacl-plugin', '')
            ];
            plugins.length = 3;
            return plugins;
        }
    });

    // 4. Realistic languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'language', { get: () => 'en-US' });

    // 5. Override permissions.query to avoid detection
    if (navigator.permissions && navigator.permissions.query) {
        const originalQuery = navigator.permissions.query.bind(navigator.permissions);
        navigator.permissions.query = (params) => {
            if (params.name === 'notifications') {
                return Promise.resolve({ state: Notification.permission });
            }
            return originalQuery(params);
        };
    }

    // 6. WebGL vendor/renderer spoofing (consistent with user-agent)
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';           // UNMASKED_VENDOR_WEBGL
        if (parameter === 37446) return 'Intel Iris OpenGL Engine'; // UNMASKED_RENDERER_WEBGL
        return getParam.call(this, parameter);
    };

    // 7. Spoof hardware concurrency and device memory
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });

    // 8. Hide automation-specific properties
    delete navigator.__proto__.webdriver;
"""


# ============================================================
#  UTILITY HELPERS
# ============================================================

async def _save_debug_screenshot(page, name):
    """Save a timestamped screenshot for troubleshooting on EC2."""
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        filepath = os.path.join(DEBUG_DIR, f"{name}.png")
        await page.screenshot(path=filepath, full_page=True)
        print(f"[BOT] 📸 Screenshot saved: {filepath}")
    except Exception as e:
        print(f"[BOT] Screenshot failed ({name}): {e}")


async def _random_delay(min_s=0.5, max_s=2.0):
    """Simulate human-like random delay between actions."""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


async def _dismiss_dialogs(page):
    """
    Dismiss any overlay dialogs that might block the join flow.
    Handles cookie consent, notification banners, sign-in prompts, etc.
    """
    dismiss_patterns = [
        # Cookie consent
        'button:has-text("Accept all")',
        'button:has-text("Accept")',
        'button:has-text("I agree")',
        # Google Meet UI dialogs
        'button:has-text("Got it")',
        'button:has-text("Dismiss")',
        'button:has-text("OK")',
        'button:has-text("Close")',
        # Guest flow
        'button:has-text("Continue without signing in")',
        'button:has-text("Skip")',
        'button:has-text("Guest")',
    ]

    dismissed_count = 0
    for pattern in dismiss_patterns:
        try:
            btn = page.locator(pattern).first
            if await btn.is_visible():
                await btn.click()
                dismissed_count += 1
                print(f"[BOT] 🗑️  Dismissed: {pattern}")
                await _random_delay(0.3, 0.8)
        except Exception:
            pass

    if dismissed_count == 0:
        print("[BOT] No overlay dialogs found")
    return dismissed_count


async def _disable_camera_and_mic(page):
    """Turn off camera and microphone in the Meet lobby (Green Room)."""

    # --- Camera ---
    camera_off = False
    camera_strategies = [
        # Strategy 1: aria-label "Turn off camera"
        'button[aria-label*="Turn off camera"]',
        # Strategy 2: case-insensitive partial match
        'button[aria-label*="turn off camera"]',
        # Strategy 3: data attribute based
        'button[data-is-muted="false"][aria-label*="camera" i]',
    ]
    for selector in camera_strategies:
        try:
            btn = page.locator(selector).first
            await btn.wait_for(state="visible", timeout=2000)
            await btn.click()
            camera_off = True
            print("[BOT] 📷 Camera turned off")
            await _random_delay(0.3, 0.5)
            break
        except Exception:
            pass
    if not camera_off:
        print("[BOT] 📷 Camera already off or toggle not found")

    # --- Microphone ---
    mic_off = False
    mic_strategies = [
        'button[aria-label*="Turn off microphone"]',
        'button[aria-label*="turn off microphone"]',
        'button[data-is-muted="false"][aria-label*="microphone" i]',
    ]
    for selector in mic_strategies:
        try:
            btn = page.locator(selector).first
            await btn.wait_for(state="visible", timeout=2000)
            await btn.click()
            mic_off = True
            print("[BOT] 🎤 Microphone turned off")
            await _random_delay(0.3, 0.5)
            break
        except Exception:
            pass
    if not mic_off:
        print("[BOT] 🎤 Microphone already off or toggle not found")


async def _enter_bot_name(page, bot_name):
    """
    Enter the bot's display name in the Meet lobby name field.
    Uses multiple selector strategies with fallbacks.
    """
    name_selectors = [
        'input[aria-label="Your name"]',
        'input[placeholder="Your name"]',
        'input[type="text"][jsname="YPqjbf"]',
    ]

    for selector in name_selectors:
        try:
            name_input = page.locator(selector).first
            await name_input.wait_for(state="visible", timeout=3000)
            await name_input.clear()

            # Type with human-like per-character delay
            for char in bot_name:
                await name_input.type(char, delay=random.randint(30, 80))

            print(f"[BOT] ✏️  Entered name: {bot_name}")
            return True
        except Exception:
            pass

    print("[BOT] ℹ️  No name input found (bot may already be logged in)")
    return False


async def _click_join_button(page):
    """
    Click the 'Ask to join' or 'Join now' button.
    Uses 4 strategies in priority order for maximum resilience.
    """

    # Strategy 1: Accessibility role with regex (most resilient to UI changes)
    try:
        join_btn = page.get_by_role(
            "button",
            name=re.compile(r"ask to join|join now", re.IGNORECASE)
        )
        await join_btn.wait_for(state="visible", timeout=5000)
        await join_btn.hover()
        await _random_delay(0.5, 1.0)
        await join_btn.click()
        print("[BOT] ✅ Clicked join button (strategy 1: get_by_role)")
        return True
    except Exception:
        pass

    # Strategy 2: aria-label attribute
    try:
        join_btn = page.locator(
            'button[aria-label*="Ask to join"], '
            'button[aria-label*="Join now"], '
            'button[aria-label*="ask to join"], '
            'button[aria-label*="join now"]'
        ).first
        await join_btn.wait_for(state="visible", timeout=3000)
        await join_btn.hover()
        await _random_delay(0.5, 1.0)
        await join_btn.click()
        print("[BOT] ✅ Clicked join button (strategy 2: aria-label)")
        return True
    except Exception:
        pass

    # Strategy 3: Text content matching
    try:
        join_btn = page.locator(
            'button:has-text("Ask to join"), button:has-text("Join now")'
        ).first
        await join_btn.wait_for(state="visible", timeout=3000)
        await join_btn.hover()
        await _random_delay(0.5, 1.0)
        await join_btn.click()
        print("[BOT] ✅ Clicked join button (strategy 3: has-text)")
        return True
    except Exception:
        pass

    # Strategy 4: Enumerate all buttons and match by text content
    try:
        buttons = await page.locator("button").all()
        for btn in buttons:
            try:
                text = (await btn.text_content() or "").strip().lower()
                if "ask to join" in text or "join now" in text:
                    if await btn.is_visible():
                        await btn.hover()
                        await _random_delay(0.5, 1.0)
                        await btn.click()
                        print(f"[BOT] ✅ Clicked join button (strategy 4: iteration, text='{text}')")
                        return True
            except Exception:
                continue
    except Exception:
        pass

    print("[BOT] ❌ Could not find the join button with any strategy")
    return False


# ============================================================
#  MAIN BOT FUNCTION
# ============================================================

async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot"):
    """
    Automates joining a Google Meet and records the raw audio using PulseAudio.
    Uses stealth techniques to avoid bot detection by Google.
    Stays in the meeting until it ends (host ends or everyone leaves).
    Returns the path to the saved audio file, or None on failure.
    """
    audio_filename = f"meeting_audio_{int(time.time())}.wav"
    temp_audio_filename = f"meeting_audio_{int(time.time())}_temp.wav"
    process = None  # FFmpeg process reference

    print(f"[BOT] ═══════════════════════════════════════════")
    print(f"[BOT] Starting bot for: {meet_url}")
    print(f"[BOT] Bot name: {bot_name}")
    print(f"[BOT] Stealth available: {HAS_STEALTH}")
    print(f"[BOT] ═══════════════════════════════════════════")

    async with async_playwright() as p:
        # --- Launch browser with anti-detection args ---
        browser = await p.chromium.launch(
            headless=False,
            args=[
                # Media stream handling
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--disable-features=AudioServiceOutOfProcess",

                # Anti-detection
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-features=ImprovedCookieControls",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-component-update",
                "--disable-features=TranslateUI",
                "--no-service-autorun",
                "--password-store=basic",

                # EC2 / Virtual display stability
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1920,1080",
                "--disable-features=VizDisplayCompositor",
            ]
        )

        # --- Create browser context ---
        context_options = {
            "permissions": ["camera", "microphone"],
            "user_agent": BOT_USER_AGENT,
            "viewport": {"width": 1920, "height": 1080},
        }

        # Reuse saved session if available (logged-in Google account)
        if os.path.exists("google_session.json"):
            print("[BOT] 🔑 Loading saved Google session...")
            context_options["storage_state"] = "google_session.json"
        else:
            print("[BOT] 👤 No saved session — joining as guest")

        context = await browser.new_context(**context_options)
        page = await context.new_page()

        # --- Apply stealth ---
        if HAS_STEALTH:
            await stealth_async(page)
            print("[BOT] 🛡️  Stealth patches applied")

        # Inject additional anti-detection scripts
        await page.add_init_script(STEALTH_INIT_SCRIPT)
        print("[BOT] 🛡️  Anti-detection scripts injected")

        try:
            # ╔═══════════════════════════════════════════╗
            # ║  STEP 1: Navigate to Google Meet          ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 1: Navigating to meeting...")
            await page.goto(meet_url, timeout=90000, wait_until="domcontentloaded")

            # Wait for network to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                print("[BOT] Network idle timeout — continuing")

            current_url = page.url
            print(f"[BOT] Page loaded — URL: {current_url}")
            await _save_debug_screenshot(page, "01_page_loaded")

            # Validate we're still on Google Meet
            if "workspace.google.com" in current_url or "meet.google.com" not in current_url:
                raise Exception(f"Redirected away from Meet → {current_url}")

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 2: Dismiss overlay dialogs          ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 2: Checking for overlay dialogs...")
            await asyncio.sleep(3)  # Let the page render overlays/popups
            await _dismiss_dialogs(page)
            await _save_debug_screenshot(page, "02_dialogs_handled")

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 3: Wait for lobby UI                ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 3: Waiting for lobby UI to appear...")
            lobby_selectors = (
                'input[aria-label="Your name"], '
                'input[placeholder="Your name"], '
                'button:has-text("Ask to join"), '
                'button:has-text("Join now"), '
                'div[data-is-meet-lobby="true"]'
            )
            try:
                await page.wait_for_selector(lobby_selectors, timeout=20000)
                print("[BOT] Lobby UI detected")
            except Exception:
                print("[BOT] ⚠️  Lobby selector timeout — trying to proceed anyway")
                await _save_debug_screenshot(page, "03_lobby_timeout")
                # Try dismissing dialogs one more time
                await _dismiss_dialogs(page)

            await _random_delay(1.0, 2.0)

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 4: Enter bot name                   ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 4: Entering bot name...")
            await _enter_bot_name(page, bot_name)
            await _random_delay(0.5, 1.0)

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 5: Disable camera & microphone      ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 5: Disabling camera and microphone...")
            await _disable_camera_and_mic(page)
            await _save_debug_screenshot(page, "04_before_join")

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 6: Click "Ask to Join" / "Join Now" ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 6: Looking for join button...")
            await _random_delay(1.0, 2.0)

            join_success = False
            for attempt in range(3):
                print(f"[BOT] Join attempt {attempt + 1}/3...")
                join_success = await _click_join_button(page)
                if join_success:
                    break

                # Between retries: dismiss any new dialogs and wait
                await _dismiss_dialogs(page)
                await _save_debug_screenshot(page, f"05_join_attempt_{attempt + 1}_failed")
                await asyncio.sleep(3)

            if not join_success:
                await _save_debug_screenshot(page, "05_join_FAILED_final")
                # Dump page HTML for remote debugging
                try:
                    html_content = await page.content()
                    os.makedirs(DEBUG_DIR, exist_ok=True)
                    dump_path = os.path.join(DEBUG_DIR, "page_dump.html")
                    with open(dump_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                    print(f"[BOT] 📄 Page HTML dumped to {dump_path}")
                except Exception:
                    pass
                raise Exception("Failed to click 'Ask to join' after 3 attempts")

            await _save_debug_screenshot(page, "06_join_clicked")

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 7: Wait for host to admit the bot   ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] Step 7: Waiting to be admitted (120s timeout)...")
            print("[BOT] ⏳ Please admit the bot from the host account!")

            try:
                await page.wait_for_function(
                    """
                    () => {
                        const buttons = Array.from(document.querySelectorAll('button'));
                        return buttons.some(b => {
                            const label = (b.getAttribute('aria-label') || '').toLowerCase();
                            const text = (b.textContent || '').toLowerCase();
                            return label.includes('leave call') ||
                                   label.includes('show everyone') ||
                                   label.includes('turn on microphone') ||
                                   label.includes('turn off microphone') ||
                                   text.includes('present now');
                        });
                    }
                    """,
                    timeout=120000,
                )
                print("[BOT] ✅ Successfully admitted to the meeting!")
            except Exception as e:
                await _save_debug_screenshot(page, "07_admission_timeout")
                print(f"[BOT] ❌ Not admitted within 120 seconds: {e}")
                return None

            await _save_debug_screenshot(page, "08_in_meeting")

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 8: Start audio recording (FFmpeg)   ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] 🎙️  Starting FFmpeg audio capture (recording until meeting ends)...")
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "pulse",           # Input: PulseAudio
                "-i", "default",         # Source: default audio sink
                "-acodec", "pcm_s16le",  # WAV format
                "-ar", "16000",          # 16kHz (optimal for speech-to-text)
                "-ac", "1",              # Mono
                temp_audio_filename,
                "-y",                    # Overwrite if exists
            ]
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            # ╔═══════════════════════════════════════════╗
            # ║  STEP 9: Monitor meeting until it ends    ║
            # ╚═══════════════════════════════════════════╝
            print("[BOT] 📍 Monitoring meeting — recording until it ends...")
            meeting_ended = False

            while not meeting_ended:
                await asyncio.sleep(5)  # Check every 5 seconds

                # Check for meeting-ended text/buttons
                meeting_end_indicators = [
                    'text="The meeting has ended"',
                    'text="You have been disconnected"',
                    'text="Meeting ended by host"',
                    'text="Meeting ended"',
                    'button:has-text("Rejoin")',
                    'button:has-text("Ask to rejoin")',
                    'button:has-text("Join again")',
                    "text=\"You'll need to rejoin\"",
                ]

                for indicator in meeting_end_indicators:
                    try:
                        element = page.locator(indicator)
                        if await element.count() > 0:
                            print(f"[BOT] 🔔 Meeting end detected: {indicator}")
                            meeting_ended = True
                            break
                    except Exception:
                        pass

                # Fallback: check if meeting controls have disappeared
                if not meeting_ended:
                    try:
                        mic_count = await page.locator(
                            'button[aria-label*="mic"], button[aria-label*="camera"]'
                        ).count()
                        details_count = await page.locator(
                            'button[aria-label="Meeting details"]'
                        ).count()

                        if mic_count == 0 and details_count == 0:
                            title = await page.title()
                            if "Meet" in title or "Google" in title:
                                print("[BOT] 🔔 Meeting UI gone — meeting likely ended")
                                meeting_ended = True
                    except Exception as e:
                        print(f"[BOT] Page check error — assuming meeting ended: {e}")
                        meeting_ended = True

            print("[BOT] Meeting ended. Stopping recording...")

            # Stop FFmpeg gracefully
            if process:
                process.terminate()
                process.wait()

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
            await _save_debug_screenshot(page, "error_final")

            # Salvage temp audio if it exists
            if os.path.exists(temp_audio_filename):
                os.rename(temp_audio_filename, audio_filename)
                print(f"[BOT] ⚠️  Partial audio saved to {audio_filename}")

            return None

        finally:
            # Ensure FFmpeg is stopped
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()

            print("[BOT] Closing browser...")
            await browser.close()


# --- Test Execution ---
if __name__ == "__main__":
    test_url = input("Paste a Google Meet link to test: ")
    asyncio.run(join_meet_and_record(test_url))