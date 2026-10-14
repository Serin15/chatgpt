"""Isolated configuration → quoted AI → immutable paper signal, desktop and mobile."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory() as folder:
        env = os.environ | {"BROWSER_TEST_DATA": folder, "AI_FIXTURE": "1"}
        for key in ("PULSE_AI_PROVIDER", "PULSE_AI_MODEL", "PULSE_AI_API_KEY", "OPENAI_API_KEY"):
            env.pop(key, None)
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
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            for _ in range(100):
                try:
                    if httpx.get(base + "/api/status", trust_env=False, timeout=1).is_success:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("AI fixture did not start")
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True, args=["--no-sandbox"]
                )
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(base)
                page.locator('.nav-item[data-page="news"]').click()
                page.locator("#news-button").click()
                page.get_by_role("button", name="Analizează pentru paper").click()
                panel = page.locator(".ai-panel")
                expect(panel).to_contain_text("AI oprit")
                page.get_by_label("Motor AI", exact=True).select_option("ollama")
                page.get_by_label("Numele exact al modelului AI").fill("test-model")
                page.get_by_role("button", name="Salvează configurația AI").click()
                expect(panel).to_contain_text("ollama · test-model")
                page.get_by_role("button", name="Testează conexiunea AI").click()
                expect(panel).to_contain_text("Conexiune testată")
                page.get_by_label("Document pentru analiza AI (URL HTTPS)").fill(
                    "https://solana.com/fixture-positive"
                )
                page.get_by_role("button", name="Analizează documentul cu AI").click()
                expect(panel.locator(".ai-result")).to_contain_text(
                    "Dovezi insuficiente pentru asociere"
                )
                expect(panel.locator(".ai-citation").first).to_contain_text(
                    "Explicit isolated source fixture"
                )
                page.get_by_label("Ipoteza de intrare").fill(
                    "Keep this cited interpretation before my manual paper decision."
                )
                page.get_by_role("button", name="Salvează semnal", exact=True).click()
                expect(page.get_by_role("button", name="Simulează intrarea")).to_be_enabled(
                    timeout=7000
                )
                export = page.request.get(base + "/api/export?account=news").json()
                captured = export["signals"][0]["evidence"]["ai_context"][0]
                assert captured["state"] == "completed" and captured["payload"]["citations_checked"]
                assert not captured["payload"]["endorsement_verified"]
                assert export["portfolio"]["cash"] == "500" and export["portfolio"]["orders"] == []
                page.get_by_label("Document pentru analiza AI (URL HTTPS)").fill(
                    "https://unapproved.example/fake"
                )
                page.get_by_role("button", name="Analizează documentul cu AI").click()
                expect(page.locator("#message")).to_contain_text("Domeniu neacceptat")
                assert page.request.get(base + "/api/ai/status").json()["requests_today"] == 1
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                assert not errors, errors
                browser.close()
                print(
                    "PASS: AI configuration, connection, exact quotations, immutable signal/export, bad host rejected, desktop/mobile, zero automatic orders. Model transport is simulated."
                )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
