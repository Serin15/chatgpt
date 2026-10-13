"""Optional UI test. Run with: uv run --with playwright python tests/browser_smoke.py"""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

root = Path(__file__).resolve().parents[1]
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
        for _ in range(50):
            try:
                if httpx.get(base + "/api/status", timeout=1).is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("Isolated fixture server failed to start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
            )
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base)
            expect(page.locator("#empty")).to_be_visible()
            page.locator("#news-button").click()
            expect(page.locator(".story")).to_have_count(1)
            expect(page.locator(".story")).to_contain_text("Asociere ipotetică")
            page.get_by_role("button", name="Analizează pentru paper").click()
            expect(page.locator("#tokens tr")).to_have_count(1)
            expect(page.locator("#detail")).to_be_visible()
            page.get_by_role("button", name="Salvează semnal").click()
            buy = page.get_by_role("button", name="Simulează intrarea")
            expect(buy).to_be_enabled(timeout=7000)
            buy.click()
            expect(page.locator("#positions")).to_contain_text("Cost intrare: 50,01")
            expect(page.locator("#cash")).to_have_text("449,99 USD")
            page.get_by_role("button", name="Simulează ieșirea").click()
            expect(page.locator("#positions")).to_contain_text("PnL net realizat")
            expect(page.locator("#cash")).not_to_have_text("500,00 USD")
            assert not errors, errors
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            browser.close()
            print(
                "PASS: isolated mocked UI headline → token hypothesis → manual $50 paper entry → exit; desktop/mobile; no JS errors"
            )
    finally:
        process.terminate()
        process.wait(timeout=10)
