"""Launch Jarvis V0.4 as a desktop app.   Run:  python app.py"""
from __future__ import annotations

import threading
import time
import urllib.request
import webbrowser

import uvicorn

import Agent
import Server

URL = f"http://127.0.0.1:{Server.PORT}"
FULLSCREEN = False   # set True for a wallpaper-style full-screen window


def wait_until_up(timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def main() -> None:
    Agent.SANDBOX.mkdir(parents=True, exist_ok=True)

    if not Agent.check_ollama():
        return

    config = uvicorn.Config(Server.app, host="127.0.0.1", port=Server.PORT, log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()

    if not wait_until_up():
        print(f"Error: the Jarvis server did not start. Is port {Server.PORT} already in use?")
        return

    print(f"Jarvis UI running at {URL}")

    try:
        import webview  # pip install pywebview
        webview.create_window(
            "Jarvis", URL, width=1440, height=900,
            fullscreen=FULLSCREEN, background_color="#05070b",
        )
        webview.start()          # blocks until the window is closed
    except Exception as exc:
        print(f"Native window unavailable ({exc}); opening your browser instead.")
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    Server.session.stop()


if __name__ == "__main__":
    main()