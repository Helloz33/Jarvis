"""Launch Jarvis as a desktop app.   Run:  python App.py"""
from __future__ import annotations

import threading
import time
import urllib.request
import webbrowser

import uvicorn

import Agent
import Server as server

URL = f"http://127.0.0.1:{server.PORT}"
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


def bring_to_front() -> None:
    """Called once the window exists; makes Jarvis the active app, so it
    still appears when it was started in the background (wake word)."""
    try:
        from AppKit import NSApplication
        from PyObjCTools import AppHelper

        AppHelper.callAfter(
            lambda: NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        )
    except Exception:
        pass


def main() -> None:
    Agent.SANDBOX.mkdir(parents=True, exist_ok=True)

    if not Agent.check_ollama():
        return

    config = uvicorn.Config(server.app, host="127.0.0.1", port=server.PORT, log_level="warning")
    threading.Thread(target=uvicorn.Server(config).run, daemon=True).start()

    if not wait_until_up():
        print(f"Error: the Jarvis server did not start. Is port {server.PORT} already in use?")
        return

    print(f"Jarvis UI running at {URL}")

    try:
        import webview  # pip install pywebview
        webview.create_window(
            "Jarvis", URL, width=1440, height=900,
            fullscreen=FULLSCREEN, background_color="#05070b",
        )
        webview.start(bring_to_front)   # blocks until the window is closed
    except Exception as exc:
        print(f"Native window unavailable ({exc}); opening your browser instead.")
        webbrowser.open(URL)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    server.session.stop()


if __name__ == "__main__":
    main()