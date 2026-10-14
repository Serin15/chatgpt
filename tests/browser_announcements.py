"""Isolated source → contract → manual relationship → immutable signal UI test."""

import json
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
            env=os.environ | {"BROWSER_TEST_DATA": folder, "ANNOUNCEMENT_FIXTURE": "1"},
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
                raise RuntimeError("Source fixture failed to start")
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
                expect(page.locator(".announcement-panel")).to_be_visible()
                source = page.get_by_label("URL-ul anunțului original")
                source.fill("https://solana.com/fixture-positive")
                page.get_by_role("button", name="Verifică anunțul și contractul").click()
                latest = page.locator(".announcement-result strong").first
                expect(latest).to_have_text("Adresă și chain găsite · emitent de evaluat")
                page.get_by_text(
                    "Evaluează manual relația sursei cu această monedă", exact=True
                ).click()
                page.get_by_label("Link de justificare pentru identitatea sursei").fill(
                    "https://example.org/isolated-identity-proof"
                )
                page.get_by_label("Cum ai verificat relația cu emitentul sau piața?").fill(
                    "Manually reviewed the source identity in this isolated fixture."
                )
                page.get_by_label("Am verificat manual identitatea sursei").check()
                page.get_by_role("button", name="Salvează evaluarea sursei").click()
                expect(page.locator(".announcement-panel")).to_contain_text(
                    "evaluare manuală activă"
                )
                page.get_by_role("button", name="Verifică anunțul și contractul").click()
                expect(latest).to_have_text("Contract găsit în sursă evaluată manual")
                page.get_by_label("Ipoteza de intrare").fill(
                    "Record exact source evidence before any paper order."
                )
                page.get_by_role("button", name="Salvează semnal").click()
                expect(page.get_by_role("button", name="Simulează intrarea")).to_be_enabled(
                    timeout=7000
                )
                export = page.request.get(base + "/api/export?account=news").json()
                captured = export["signals"][0]["evidence"]["research_context"]["announcements"][
                    "checks"
                ][0]
                assert (
                    captured["effective_status"] == "manual_source_match"
                    and captured["payload"]["document"]["sha256"]
                )
                assert export["portfolio"]["orders"] == [] and export["portfolio"]["cash"] == "500"
                page.get_by_role("button", name="Retrage evaluarea sursei").click()
                expect(latest).to_have_text("Evaluarea sursei a expirat sau a fost retrasă")
                source.fill("https://solana.com/fixture-negative")
                page.get_by_role("button", name="Verifică anunțul și contractul").click()
                expect(latest).to_have_text("Context de avertizare sau negare · necesită evaluare")
                page.set_viewport_size({"width": 390, "height": 844})
                assert page.evaluate("document.documentElement.scrollWidth") == 390
                assert not errors, errors
                assert (
                    json.loads(page.request.get(base + "/api/export?account=news").text())[
                        "signals"
                    ][0]["evidence"]["research_context"]["announcements"]["checks"][0][
                        "effective_status"
                    ]
                    == "manual_source_match"
                )
                browser.close()
                print(
                    "PASS: original document, exact contract, manual source review, revocation, negative context, immutable signal/export, mobile, no orders"
                )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
