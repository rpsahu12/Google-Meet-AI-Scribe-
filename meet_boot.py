import asyncio
import subprocess
import os
import time
from playwright.async_api import async_playwright

async def join_meet_and_record(meet_url: str, bot_name: str = "AI Scribe Bot"):
    """
    Automates joining a Google Meet and records the raw audio using Ubuntu's PulseAudio.
    Stays in the meeting until it ends (host ends or everyone leaves).
    """
    # Create a unique filename based on timestamp
    audio_filename = f"meeting_audio_{int(time.time())}.wav"
    temp_audio_filename = f"meeting_audio_{int(time.time())}_temp.wav"

    print(f"Starting bot for URL: {meet_url}")

    async with async_playwright() as p:
        # Launch Chromium with anti-detection measures
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--disable-features=AudioServiceOutOfProcess",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-web-security",
                "--disable-features=ImprovedCookieControls",
                "--no-first-run",
                "--no-default-browser-check"
            ]
        )

        # Use a realistic user agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        # Optional: Load saved Google session if available
        context_options = {
            'permissions': ['camera', 'microphone'],
            'user_agent': user_agent,
            'viewport': {'width': 1920, 'height': 1080}
        }
        if os.path.exists("google_session.json"):
            print("Loading saved Google session...")
            context_options['storage_state'] = "google_session.json"
        else:
            print("No Google session found - joining as guest")

        context = await browser.new_context(**context_options)

        # Add extra headers to look like a real browser
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)

        page = await context.new_page()

        # Inject anti-detection script
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        try:
            print("Navigating to meeting...")

            # First, try to load with domcontentloaded (faster)
            await page.goto(meet_url, timeout=90000, wait_until="domcontentloaded")

            # Then wait for network idle with longer timeout
            try:
                await page.wait_for_load_state("networkidle", timeout=60000)
            except:
                print("Network idle timeout, but continuing...")
                pass

            current_url = page.url
            print(f"Page loaded successfully. Title: {await page.title()}")
            print(f"Current URL: {current_url}")

            # Check if we got redirected (invalid meeting link)
            if "workspace.google.com" in current_url or "meet.google.com" not in current_url:
                raise Exception(f"Invalid or expired meeting link - redirected to {current_url}")

            # Wait for the main content container to appear
            print("Waiting for meeting lobby UI...")
            try:
                await page.wait_for_selector('div[role="main"], div.TZFSLb, div[data-is-meet-lobby="true"]', timeout=15000)
            except:
                pass  # Continue anyway

            # 0. Wait for and dismiss any sign-in dialog first
            print("Checking for sign-in prompt...")

            # Try to find and click "Skip" or "Continue without signing in" if available
            try:
                # Look for "Continue without signing in" or similar
                skip_button = page.locator('button:has-text("Continue without signing in"), button:has-text("Skip"), button:has-text("Guest")')
                if await skip_button.count() > 0:
                    await skip_button.click()
                    await asyncio.sleep(2)
                    print("Clicked skip sign-in button")
            except:
                pass

            # 1. Enter Name (Conditional based on login status)
            print("Checking if name input is required...")
            name_box = page.locator('input[placeholder="Your name"], input[aria-label="Your name"], input[type="text"][jsname="YPqjbf"]')
            
            try:
                # Only wait 5 seconds. If we are logged in, this box won't exist!
                await name_box.wait_for(state="visible", timeout=5000)
                print("Typing bot name...")
                await name_box.fill(bot_name)
                print(f"Filled name: {bot_name}")
            except:
                print("No name input required (Bot is already logged in!). Skipping to Join...")

            # 2. Ask to Join
            print("Clicking 'Ask to join'. Please admit the bot from your host account!")
            await asyncio.sleep(2)
            join_button = page.locator('button:has-text("Ask to join"), button:has-text("Join now")').first
            await join_button.evaluate("node => node.click()")

            # 3. Wait for Admission (we just wait for the network to stop loading after you admit it)
            print("Waiting for you to click Admit... (60 second timeout)")
            
            # We wrap this in a try/except because we just want to wait, we don't care if it errors on a specific button
            try:
                # Wait until the page fully stabilizes, meaning it has loaded the actual video room
                await page.wait_for_load_state("networkidle", timeout=60000)
            except:
                pass # If it times out but still got in, we just keep going

            print("Assuming bot is in the meeting! 🎙️ Starting FFmpeg audio capture...")

            # 4. Start Audio Recording (no time limit - will run until meeting ends)
            print("🎙️ Starting FFmpeg audio capture (recording until meeting ends)...")
            # This captures the default PulseAudio output (what the browser hears)
            ffmpeg_cmd = [
                "ffmpeg",
                "-f", "pulse",          # Input format: PulseAudio
                "-i", "default",        # Input source: Default audio sink
                "-acodec", "pcm_s16le", # WAV format
                "-ar", "16000",         # 16kHz (Optimal for speech-to-text models)
                "-ac", "1",             # Mono
                temp_audio_filename,
                "-y"                    # Overwrite
            ]

            # Launch FFmpeg in the background
            process = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 5. Monitor meeting status - stay until meeting ends
            print("📍 Monitoring meeting status...")
            meeting_ended = False

            while not meeting_ended:
                await asyncio.sleep(5)  # Check every 5 seconds

                # Check for various meeting-ended indicators
                meeting_end_indicators = [
                    'text="The meeting has ended"',
                    'text="You have been disconnected"',
                    'text="Meeting ended by host"',
                    'text="Meeting ended"',
                    'button:has-text("Rejoin")',
                    'button:has-text("Ask to rejoin")',
                    'button:has-text("Join again")',
                    'text="Youll need to rejoin"',
                ]

                # Check if any meeting end indicator is present
                for indicator in meeting_end_indicators:
                    try:
                        element = page.locator(indicator)
                        if await element.count() > 0:
                            print("Meeting end detected!")
                            meeting_ended = True
                            break
                    except:
                        pass

                # Also check if we've been kicked out (page redirected or meeting UI gone)
                try:
                    # Check for meeting controls (mic/camera buttons that appear during active meeting)
                    mic_button = await page.locator('button[aria-label*="mic"], button[aria-label*="camera"]').count()
                    meeting_details = await page.locator('button[aria-label="Meeting details"]').count()

                    # If no meeting controls AND no meeting details button, meeting likely ended
                    if mic_button == 0 and meeting_details == 0:
                        # Double-check by looking for end-of-meeting page structure
                        title = await page.title()
                        if "Meeting" in title or "Google Meet" in title:
                            print("Meeting UI no longer present - meeting may have ended")
                            meeting_ended = True
                except Exception as e:
                    print(f"Page navigation detected - checking if meeting ended: {e}")
                    meeting_ended = True

            print("Meeting ended. Stopping recording...")

            # Ensure FFmpeg closes properly
            process.terminate()
            process.wait()

            # Convert temp file to final file if needed
            if os.path.exists(temp_audio_filename):
                os.rename(temp_audio_filename, audio_filename)
                print(f"✅ Audio successfully saved to {audio_filename}")
                return audio_filename
            else:
                print("❌ Failed to save audio file.")
                return None

        except Exception as e:
            print(f"An error occurred: {e}")
            # Save screenshot for debugging
            try:
                await page.screenshot(path="error_screenshot.png")
                print("Screenshot saved to error_screenshot.png for debugging")
            except:
                pass
            # Clean up temp file on error
            if os.path.exists(temp_audio_filename):
                os.rename(temp_audio_filename, audio_filename)
            return None

        finally:
            print("Closing browser...")
            await browser.close()

# --- Test Execution ---
if __name__ == "__main__":
    # Create a dummy Google Meet manually, copy the link, and paste it here
    test_url = input("Paste a Google Meet link to test: ")
    asyncio.run(join_meet_and_record(test_url))