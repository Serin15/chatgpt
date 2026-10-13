"""Start the local application and open its browser tab. No external deployment."""

import argparse
import socket
import subprocess
import sys
import time
import webbrowser

import httpx


def our_app(url):
    try:
        response = httpx.get(url + "/openapi.json", timeout=1, trust_env=False)
        return (
            response.is_success
            and response.json().get("info", {}).get("title") == "Memecoin Research · Paper only"
        )
    except (httpx.HTTPError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description="Start Memecoin Research on this computer")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65525:
        parser.error("Port must be between 1024 and 65525")
    for port in range(args.port, args.port + 10):
        url = f"http://127.0.0.1:{port}"
        if our_app(url):
            print(f"Application already running on local port {port}.", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                break
            except OSError:
                continue
    else:
        print("No available local port. Close an older instance or use --port.")
        return 1
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ]
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                return process.returncode
            if our_app(url):
                print(
                    f"Ready. Open localhost:{port} in your browser. Keep this window open; Ctrl+C stops the app.",
                    flush=True,
                )
                if not args.no_browser:
                    webbrowser.open(url)
                return process.wait()
            time.sleep(0.1)
        print("The application did not become ready within the startup deadline.")
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    raise SystemExit(main())
