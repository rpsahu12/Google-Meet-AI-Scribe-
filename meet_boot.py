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
            await page.goto(meet_url, timeout=90000, wait_until="load")

            # Wait for page to be fully interactive
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)  # Extra buffer for Google Meet's JS to initialize

            # 1. Enter Name
            print("Typing bot name...")
            name_box = page.locator('input[placeholder="Your name"]:visible')
            await name_box.wait_for(state="visible", timeout=45000)
            await name_box.wait_for(state="stable", timeout=5000)  # Wait for element to be stable
            await name_box.click()  # Focus first
            await asyncio.sleep(0.5)
            await name_box.fill(bot_name)

            # 2. Ask to Join
            print("Clicking 'Ask to join'. Please admit the bot from your host account!")
            await asyncio.sleep(2)
            join_button = page.locator('button:has-text("Ask to join"), button:has-text("Join now")').first
            await join_button.click(force=True)

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