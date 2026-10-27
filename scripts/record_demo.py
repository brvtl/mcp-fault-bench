"""Capture the local replay as H.264 MP4, GIF, and two key frames (scoreboard.png, lanes.png).

Start the server first: python -m mcp_fault_bench serve --port 8787 (override the page with DEMO_URL).
"""

import asyncio
import os
import subprocess
from pathlib import Path

from playwright.async_api import async_playwright

ROOT=Path(__file__).resolve().parents[1]
MEDIA=ROOT/"media"
URL=os.getenv("DEMO_URL","http://127.0.0.1:8787/?replay=1")

async def main():
    MEDIA.mkdir(exist_ok=True)
    for stale in MEDIA.glob("*.webm"):
        stale.unlink()
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(viewport={"width":1280,"height":720},record_video_dir=str(MEDIA),record_video_size={"width":1280,"height":720})
        page=await context.new_page()
        await page.goto(URL,wait_until="networkidle")
        await page.wait_for_timeout(5000)
        await page.wait_for_timeout(6000)
        await page.screenshot(path=str(MEDIA/"lanes.png"))
        # The replay is 24 s and ends on the faulted-only chart (from summary.json).
        await page.wait_for_timeout(12500)
        await context.close()
        # Scoreboard still from the static (non-replay) page, full page height so no panel is cropped.
        still=await browser.new_page(viewport={"width":1280,"height":720})
        await still.goto(URL.replace("?replay=1",""),wait_until="networkidle")
        await still.wait_for_timeout(1500)
        await still.screenshot(path=str(MEDIA/"scoreboard.png"),full_page=True)
        await browser.close()
    recordings=list(MEDIA.glob("*.webm"))
    if not recordings:
        raise RuntimeError("Playwright did not produce a replay recording")
    webm=recordings[0]
    mp4=MEDIA/"demo.mp4"
    subprocess.run(["/usr/bin/ffmpeg","-y","-i",str(webm),"-vf","format=yuv420p","-c:v","libx264","-movflags","+faststart",str(mp4)],check=True)
    palette=MEDIA/"palette.png"
    subprocess.run(["/usr/bin/ffmpeg","-y","-i",str(mp4),"-vf","fps=12,scale=960:-1:flags=lanczos,palettegen",str(palette)],check=True)
    subprocess.run(["/usr/bin/ffmpeg","-y","-i",str(mp4),"-i",str(palette),"-filter_complex","fps=12,scale=960:-1:flags=lanczos[x];[x][1:v]paletteuse","-loop","0",str(MEDIA/"demo.gif")],check=True)
    webm.unlink(missing_ok=True);palette.unlink(missing_ok=True)

if __name__=="__main__":asyncio.run(main())
