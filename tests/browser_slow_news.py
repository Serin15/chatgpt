"""Real browser: an indefinitely delayed news response must not delay healthy sections."""

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright, expect

root = Path(__file__).resolve().parents[1]


async def check(base):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
        )
        page = await browser.new_page()
        gate = asyncio.Event()

        async def delayed_news(route):
            await gate.wait()
            await route.fulfill(status=200, content_type="application/json", body="[]")

        await page.route("**/api/news?archive=false", delayed_news)
        try:
            await page.goto(base)
            await page.locator('.nav-item[data-page="market"]').click()
            await expect(page.locator("#asset-rows tr").first).to_be_visible(timeout=2000)
            assert not gate.is_set()
            print(
                "PASS: healthy market section rendered while news response remained blocked; real Chromium, fake data"
            )
        finally:
            gate.set()
            await browser.close()


with socket.socket() as probe:
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
with tempfile.TemporaryDirectory() as folder:
    environment = os.environ.copy()
    environment["BROWSER_TEST_DATA"] = folder
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.browser_fixture:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=root,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(base + "/healthz", timeout=1).is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("fixture startup failed")
        httpx.post(base + "/api/assets/refresh", json={}).raise_for_status()
        asyncio.run(check(base))
    finally:
        process.terminate()
        process.wait(timeout=10)
