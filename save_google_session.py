"""
One-time script to save Google session cookies for the Meet bot.

Run this locally (not on AWS) with:
    python save_google_session.py

It will open a browser, you log in to Google, and then close the browser.
The session will be saved to 'google_session.json' which can be used by meet_boot.py
"""

import asyncio
import json
from playwright.async_api import async_playwright


async def save_google_session():
    print("Opening browser... Please log in to Google when prompted.")
    print("After logging in, navigate to https://meet.google.com and then close the browser.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,  # You need to see it to log in
            args=[
                "--disable-blink-features=AutomationControlled"
            ]
        )

        context = await browser.new_context()
        page = await context.new_page()

        # Go to Google Meet
        print("Navigating to Google Meet...")
        await page.goto("https://meet.google.com", wait_until="load")

        # Wait for user to log in
        print("\n" + "="*60)
        print("INSTRUCTIONS:")
        print("1. If prompted, sign in with your Google account")
        print("2. Grant any permissions requested (camera/mic)")
        print("3. Once you see the Meet homepage, close the browser window")
        print("="*60 + "\n")

        # Wait for page to close (user closes browser when done)
        try:
            await page.wait_for_event("close", timeout=300000)  # 5 minute timeout
        except:
            pass  # User might close via other means

        # Save storage state (cookies, localStorage, etc.)
        storage_state = await context.storage_state()

        # Save to file
        with open("google_session.json", "w") as f:
            json.dump(storage_state, f, indent=2)

        print("\nSession saved to 'google_session.json'")
        print("Copy this file to your AWS server and the bot will use it to stay logged in.")


if __name__ == "__main__":
    asyncio.run(save_google_session())
