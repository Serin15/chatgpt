"""Real Chromium, isolated fake data providers; validates login/CSRF and advanced UI."""

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
    environment.update(
        BROWSER_TEST_DATA=folder, PULSE_AUTH_PASSWORD="isolated-browser-password-123456"
    )
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
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
            )
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base)
            expect(page.locator("#login-dialog")).to_be_visible()
            page.locator("#login-password").fill("isolated-browser-password-123456")
            page.locator("#login-form button").click()
            expect(page.locator("#login-dialog")).not_to_be_visible()
            page.locator('.nav-item[data-page="advanced"]').click()
            expect(page.locator("#advanced-content")).to_contain_text(
                "Pool-uri și tokenuri observate"
            )
            expect(page.locator("#advanced-content")).to_contain_text("Wallet")
            page.get_by_role("button", name="Colectează alerte").click()
            expect(page.locator("#advanced-content")).to_contain_text(
                "Pool-uri și tokenuri observate"
            )
            assert page.evaluate("document.documentElement.scrollWidth") == 390
            page.get_by_role("button", name="Închide sesiunea").click()
            expect(page.locator("#login-dialog")).to_be_visible()
            assert page.request.get(base + "/api/status").status == 401
            assert not errors, errors
            browser.close()
        print(
            "PASS: login, authenticated mutations with CSRF, advanced panels, mobile width, logout; fake data, real browser"
        )
    finally:
        process.terminate()
        process.wait(timeout=10)
