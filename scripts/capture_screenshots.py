from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parents[1]
SCREENSHOTS_DIR = BASE_DIR / "assets" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main():
    print("Starting Streamlit process...")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app.py",
        "--server.port=8501",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    st_proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Wait for server to start
    time.sleep(4)

    try:
        with sync_playwright() as p:
            print("Launching Edge browser via Playwright...")
            browser = p.chromium.launch(
                executable_path=EDGE_PATH,
                headless=True,
                args=["--disable-gpu", "--no-sandbox"],
            )
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            page = context.new_page()

            print("Navigating to http://localhost:8501...")
            page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)

            # Wait for empty drop zone to appear
            page.wait_for_selector(".empty-drop-zone", timeout=15000)
            time.sleep(1.5)

            # 1. Empty state screenshot
            print("Capturing 1/5: empty_state.png")
            page.screenshot(path=str(SCREENSHOTS_DIR / "empty_state.png"))

            # Trigger analysis by clicking "Start Analysis" in sidebar
            print("Clicking Start Analysis...")
            start_btn = page.locator('button:has-text("Start Analysis")')
            if start_btn.count() > 0:
                start_btn.first.click()
            else:
                page.locator('button:has-text("Try Sample Meeting")').first.click()

            # Wait briefly to capture active processing state
            time.sleep(1.0)
            print("Capturing 2/5: processing_state.png")
            page.screenshot(path=str(SCREENSHOTS_DIR / "processing_state.png"))

            # Wait for analysis to complete and results to render
            print("Waiting for analysis to complete...")
            page.wait_for_selector(".stat-row", timeout=60000)
            time.sleep(2)

            # 3. Minutes tab screenshot
            print("Capturing 3/5: minutes_tab.png")
            page.screenshot(path=str(SCREENSHOTS_DIR / "minutes_tab.png"))

            # 4. Transcript tab screenshot
            print("Clicking Transcript tab...")
            tab_transcript = page.locator('button[role="tab"]:has-text("Transcript")')
            if tab_transcript.count() > 0:
                tab_transcript.first.click()
                time.sleep(1.5)
                print("Capturing 4/5: transcript_tab.png")
                page.screenshot(path=str(SCREENSHOTS_DIR / "transcript_tab.png"))

            # 5. Speakers tab screenshot
            print("Clicking Speakers tab...")
            tab_speakers = page.locator('button[role="tab"]:has-text("Speakers")')
            if tab_speakers.count() > 0:
                tab_speakers.first.click()
                time.sleep(1.5)
                # Scroll slightly to show talk-time bars nicely
                page.evaluate("window.scrollBy(0, 120)")
                time.sleep(0.5)
                print("Capturing 5/5: speakers_tab.png")
                page.screenshot(path=str(SCREENSHOTS_DIR / "speakers_tab.png"))

            browser.close()
    finally:
        print("Terminating Streamlit process...")
        st_proc.terminate()
        try:
            st_proc.wait(timeout=5)
        except Exception:
            st_proc.kill()

    print("All 5 screenshots captured successfully in assets/screenshots/")


if __name__ == "__main__":
    main()
