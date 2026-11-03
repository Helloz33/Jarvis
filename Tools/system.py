"""Everything that differs between macOS, Windows and Linux lives here, in one place.

The rest of Jarvis calls these four functions and never checks the operating system itself:

    speak(text, voice, on_start)   say it out loud (interruptible: on_start gets the process)
    notify(text)                   a silent desktop notification
    app_running(script)            is "App.py" running right now?

macOS is the tested path. The Windows and Linux versions are written from the platform docs and
have NOT been run on a real machine yet, so treat them as experimental until someone has.
"""
from __future__ import annotations

import os
import subprocess
import sys

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
NAME = "macOS" if IS_MAC else "Windows" if IS_WIN else "Linux"

_PS = ["powershell", "-NoProfile", "-NonInteractive", "-Command"]
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)       # hide the PowerShell console on Windows


def _run(cmd: list[str], env: dict | None = None, wait: bool = True, timeout: int = 60):
    """Start a command. Returns the process (finished if wait=True) or None if it cannot start."""
    full_env = dict(os.environ, **(env or {}))
    try:
        proc = subprocess.Popen(cmd, env=full_env, creationflags=_NO_WINDOW if IS_WIN else 0,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError):
        return None
    if wait:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc


# --- speaking ---------------------------------------------------------------------------
def _speech_command(text: str, voice: str) -> tuple[list[str], dict] | None:
    if IS_MAC:
        return (["say", "-v", voice, text] if voice else ["say", text]), {}
    if IS_WIN:
        script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "if ($env:JARVIS_VOICE) { try { $s.SelectVoice($env:JARVIS_VOICE) } catch {} }; "
                  "$s.Speak($env:JARVIS_TEXT)")
        return _PS + [script], {"JARVIS_TEXT": text, "JARVIS_VOICE": voice or ""}
    for tool in ("espeak-ng", "espeak", "spd-say"):
        if _which(tool):
            return [tool, text], {}
    return None


def _which(tool: str) -> bool:
    from shutil import which
    return which(tool) is not None


def speak(text: str, voice: str = "", on_start=None) -> bool:
    """Speak and wait until it is done. on_start(process) is called as soon as speech begins, so the
    caller can interrupt it with process.terminate(). Returns False if this system cannot speak this
    way (the caller then falls back to pyttsx3)."""
    text = (text or "").strip()
    if not text:
        return True
    built = _speech_command(text, voice)
    if built is None:
        return False
    cmd, env = built
    proc = _run(cmd, env, wait=False)
    if proc is None:
        return False
    if on_start:
        on_start(proc)
    proc.wait()
    if IS_MAC and voice and proc.returncode and proc.returncode > 0:
        # That voice is not installed on this Mac: say it with the system default.
        retry = _run(["say", text], wait=False)
        if retry is not None:
            if on_start:
                on_start(retry)
            retry.wait()
    return True


# --- notifications -----------------------------------------------------------------------
def notify(text: str, title: str = "Jarvis") -> None:
    """A silent notification in the corner of the screen. Never raises."""
    try:
        if IS_MAC:
            script = 'on run argv\ndisplay notification (item 1 of argv) with title (item 2 of argv)\nend run'
            _run(["osascript", "-e", script, text, title], timeout=10)
        elif IS_WIN:
            script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                      "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
                      "$n.Visible = $true; $n.ShowBalloonTip(6000, $env:JARVIS_TITLE, $env:JARVIS_TEXT, 'Info'); "
                      "Start-Sleep -Seconds 7; $n.Dispose()")
            _run(_PS + [script], {"JARVIS_TEXT": text, "JARVIS_TITLE": title}, wait=False)
        elif _which("notify-send"):
            _run(["notify-send", title, text], timeout=10)
    except Exception:
        pass


# --- is the app running? -----------------------------------------------------------------
def app_running(script: str = "App.py") -> bool:
    try:
        if IS_WIN:
            query = ("(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*" + script.replace("'", "") +
                     "*' -and $_.ProcessId -ne $PID }).Count")
            out = subprocess.run(_PS + [query], capture_output=True, text=True, timeout=15,
                                 creationflags=_NO_WINDOW).stdout.strip()
            return out.isdigit() and int(out) > 0
        return subprocess.run(["pgrep", "-f", script], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return False