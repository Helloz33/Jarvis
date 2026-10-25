"""Jarvis V0.4 backend: serves the HUD and bridges it to your existing agent.

Agent.py's logic is untouched. We wrap the functions in Agent.FUNCTIONS so every
tool call is logged and pushed to the UI, and we register a confirmation
handler so edits/deletes show the Yes/No popup instead of a terminal prompt.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import Agent
import Memory
from Personality import AUTO_LISTEN_ON_START, VOICE, greeting
from Tools import SANDBOX, listen, reminders, set_confirm_handler, speak
from Tools.schedule import week_view

PORT = 8765
ITERATION = "V0.6"
ROOT = Path(__file__).resolve().parent
UI_FILE = ROOT / "ui" / "index.html"
LOG_FILE = ROOT / "logs" / "logbook.jsonl"
EXIT_WORDS = {"exit", "quit", "bye"}
CONFIRM_TIMEOUT_SECONDS = 120
# Only pages served by this app may open the WebSocket (stops other websites
# open in your browser from talking to Jarvis).
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

CATEGORY = {
    "list_files": "FILES", "read_file": "FILES", "create_file": "FILES",
    "edit_file": "FILES", "delete_file": "FILES",
    "run_python": "RUN", "web_search": "WEB", "get_time": "RUN",
    "remember": "MEMORY", "recall": "MEMORY", "forget": "MEMORY",
    "list_schedule": "RUN", "add_event": "RUN", "update_event": "RUN",
    "delete_event": "RUN", "set_goal": "RUN", "set_day_off": "RUN", "adjust_homework": "RUN", "plan_week": "RUN",
}


def classify(result) -> str:
    if not isinstance(result, str):
        return "ok"
    r = result.strip()
    if r.startswith("Exit code:"):
        return "ok" if r.startswith("Exit code: 0") else "error"
    if r.startswith("Error"):
        return "error"
    if r.startswith(("Deleted ", "Forgot ")):
        return "deleted"
    if r.startswith("Remembered"):
        return "approved"
    if r.startswith("Edited "):
        return "approved"
    if "cancelled" in r[:30].lower():
        return "denied"
    return "ok"


def describe(name: str, kwargs: dict, result) -> str:
    if name == "web_search":
        return str(kwargs.get("query", ""))
    if name == "get_time":
        return str(kwargs.get("timezone", "")) or "local time"
    if name == "list_files":
        return "Test/"
    if name == "remember":
        return str(kwargs.get("fact", ""))
    if name == "recall":
        return str(kwargs.get("query", ""))
    if name == "forget":
        return str(kwargs.get("memory_id", ""))
    if name in ("add_event", "set_goal"):
        return str(kwargs.get("title", ""))
    if name == "adjust_homework":
        return f"{kwargs.get('minutes', '')} min {kwargs.get('date', 'today')}"
    if name == "set_day_off":
        return str(kwargs.get("start_date", ""))
    if name in ("update_event", "delete_event"):
        return str(kwargs.get("event_id", ""))
    if name in ("list_schedule", "plan_week"):
        return str(kwargs.get("start_date", "")) or "this week"
    detail = str(kwargs.get("path", ""))
    if name == "run_python" and isinstance(result, str) and result:
        detail += f"  ({result.splitlines()[0]})"
    return detail


class Hub:
    """Shared state + thread-safe broadcasting to every connected UI."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[WebSocket] = set()
        self.started = time.time()
        self.state = "idle"
        self.latency_ms: int | None = None
        self.counts = {"FILES": 0, "RUN": 0, "WEB": 0, "MEMORY": 0, "VOICE": 0}
        self.logs: list[dict] = []
        self.pending: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()
        self._load_logs()

    def _load_logs(self) -> None:
        if not LOG_FILE.exists():
            return
        try:
            for line in LOG_FILE.read_text(encoding="utf-8").splitlines()[-500:]:
                entry = json.loads(line)
                self.logs.append(entry)
                self.counts[entry["cat"]] = self.counts.get(entry["cat"], 0) + 1
        except (OSError, ValueError, KeyError):
            pass

    def file_count(self) -> int:
        try:
            return sum(
                1 for p in SANDBOX.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            )
        except OSError:
            return 0

    def snapshot(self) -> dict:
        home = str(Path.home())
        return {
            "type": "snapshot",
            "model": Agent.MODEL,
            "iteration": ITERATION,
            "sandbox": str(SANDBOX).replace(home, "~"),
            "files": self.file_count(),
            "calls": len(self.logs),
            "counts": self.counts,
            "memory": Memory.stats(),
            "pending": len(self.pending),
            "state": self.state,
            "started": self.started,
            "latency_ms": self.latency_ms,
            "logs": list(reversed(self.logs[-200:])),
        }

    # -- broadcasting ----------------------------------------------------
    def emit(self, event: dict) -> None:
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self._broadcast(event), self.loop)

    async def _broadcast(self, event: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:
                self.clients.discard(ws)

    def set_state(self, state: str) -> None:
        self.state = state
        self.emit({"type": "state", "state": state})

    def toast(self, text: str) -> None:
        self.emit({"type": "toast", "text": text})

    def add_log(self, tool: str, cat: str, detail: str, result: str) -> None:
        entry = {
            "t": time.strftime("%H:%M:%S"), "ts": time.time(),
            "tool": tool, "cat": cat, "d": detail, "r": result,
        }
        with self._lock:
            self.logs.append(entry)
            self.counts[cat] = self.counts.get(cat, 0) + 1
            try:
                LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with LOG_FILE.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError:
                pass
        self.emit({
            "type": "log", "entry": entry, "calls": len(self.logs),
            "counts": self.counts, "files": self.file_count(),
            "memory": Memory.stats(),
        })


hub = Hub()


SCHEDULE_TOOLS = {"add_event", "update_event", "delete_event", "set_goal", "set_day_off", "adjust_homework", "plan_week"}


def instrument_tools() -> None:
    """Wrap every Agent tool so calls are logged and sent to the UI."""
    def make(name, fn):
        def wrapped(**kwargs):
            try:
                result = fn(**kwargs)
            except Exception:
                hub.add_log(name, CATEGORY.get(name, "FILES"),
                            describe(name, kwargs, ""), "error")
                raise
            hub.add_log(name, CATEGORY.get(name, "FILES"),
                        describe(name, kwargs, result), classify(result))
            if name in SCHEDULE_TOOLS:
                hub.emit(schedule_view())   # keep the SCHEDULE tab live
            return result
        return wrapped

    for name, fn in list(Agent.FUNCTIONS.items()):
        Agent.FUNCTIONS[name] = make(name, fn)


def on_memory_event(kind: str, detail: str) -> None:
    """Automatic memory activity (auto-recall, session summaries) -> Log Book."""
    names = {
        "auto_recall": ("memory_recall", "ok"),
        "summary": ("session_summary", "approved"),
        "summary_error": ("session_summary", "error"),
    }
    tool, result = names.get(kind, (kind, "ok"))
    hub.add_log(tool, "MEMORY", detail, result)


def memory_list() -> dict:
    items = sorted(Memory.store.load_memories(), key=lambda m: m["created"], reverse=True)
    return {
        "type": "memories",
        "items": [
            {"id": m["id"], "text": m["text"], "created": m["created"], "source": m.get("source", "")}
            for m in items
        ],
        "profile": Memory.store.read_profile(),
        "stats": Memory.stats(),
    }


def schedule_view(start: str = "") -> dict:
    view = week_view(start)
    view["type"] = "schedule"
    return view


def confirm(action: str, path: str, detail: str) -> bool:
    """Called from the agent thread. Blocks until the UI answers (or times out)."""
    req_id = uuid.uuid4().hex[:8]
    event, box = threading.Event(), {"ok": False}
    hub.pending[req_id] = (event, box)
    hub.set_state("confirm")
    hub.emit({"type": "confirm", "id": req_id, "action": action,
              "file": path, "detail": detail, "pending": len(hub.pending)})
    event.wait(timeout=CONFIRM_TIMEOUT_SECONDS)   # a timeout counts as "no"
    hub.pending.pop(req_id, None)
    hub.emit({"type": "confirm_done", "id": req_id, "pending": len(hub.pending)})
    hub.set_state("thinking")
    return box["ok"]


class Session:
    """Runs the listen -> think -> speak loop in background threads."""

    def __init__(self) -> None:
        self.sid = 0
        self.lock = threading.Lock()
        self.say_proc: subprocess.Popen | None = None
        self.greeted = False
        self.reminder_lines: list[str] = []

    def _new_sid(self) -> int:
        with self.lock:
            self.sid += 1
            return self.sid

    def toggle(self) -> None:
        if hub.state == "idle":
            self.start_listening()
        else:
            self.stop()

    def start_listening(self, greeting_text: str = "") -> None:
        """Start the voice loop, optionally greeting the user first."""
        if hub.state != "idle":
            return
        sid = self._new_sid()
        threading.Thread(
            target=self._voice_loop, args=(sid, greeting_text), daemon=True
        ).start()

    def stop(self) -> None:
        self._new_sid()                      # invalidates any running loop
        self._kill_speech()
        for event, box in list(hub.pending.values()):
            box["ok"] = False                # stopping denies open requests
            event.set()
        hub.set_state("idle")

    def say(self, text: str) -> None:
        """Typed fallback (open the UI with #dev) for testing without a mic."""
        text = text.strip()
        if not text:
            return
        sid = self._new_sid()

        def work():
            hub.emit({"type": "heard", "text": text})
            self._turn(text, sid)
            if sid == self.sid:
                hub.set_state("idle")

        threading.Thread(target=work, daemon=True).start()

    def remind(self, item: dict) -> None:
        """A schedule reminder is due (called from the reminder thread)."""
        hub.add_log("reminder", "RUN", item["title"], "quiet" if item["quiet"] else "spoken")
        hub.toast(item["text"])
        reminders.notify(item["text"])
        if item["quiet"]:
            return
        with self.lock:
            self.reminder_lines.append(item["text"])
        if hub.state == "idle":
            self.say_reminders()             # otherwise the voice loop says it between turns

    def say_reminders(self) -> None:
        was = hub.state
        while True:
            with self.lock:
                text = self.reminder_lines.pop(0) if self.reminder_lines else ""
            if not text:
                break
            hub.set_state("speaking")
            hub.emit({"type": "reply", "text": text, "latency_ms": hub.latency_ms})
            self._speak(text)
        if hub.state == "speaking":
            hub.set_state(was if was in ("idle", "listening") else "idle")

    def announce(self, text: str) -> None:
        """Speak a short status line (e.g. "Searching for...") mid-turn."""
        hub.set_state("speaking")
        self._speak(text)
        hub.set_state("thinking")

    def _voice_loop(self, sid: int, greeting_text: str = "") -> None:
        try:
            if greeting_text:
                time.sleep(1.5)              # let the wake-up animation play
                if sid != self.sid:
                    return
                hub.set_state("speaking")
                hub.emit({"type": "reply", "text": greeting_text, "latency_ms": hub.latency_ms})
                self._speak(greeting_text)
            while sid == self.sid:
                if self.reminder_lines:
                    self.say_reminders()
                    if sid != self.sid:
                        return
                hub.set_state("listening")
                try:
                    text = listen()
                except RuntimeError as exc:
                    hub.toast(str(exc))
                    break
                if sid != self.sid:
                    return
                if not text:
                    continue
                hub.add_log("speech_to_text", "VOICE", f'heard: "{text}"', "ok")
                hub.emit({"type": "heard", "text": text})
                if text.strip().lower().strip(".!?, ") in EXIT_WORDS:
                    # Summarize while "Goodbye" is being spoken.
                    Memory.end_session(Agent.MODEL, on_done=lambda: hub.emit(memory_list()))
                    self._speak("Goodbye.")
                    break
                if not self._turn(text, sid):
                    return
        finally:
            if sid == self.sid:
                hub.set_state("idle")

    def _turn(self, text: str, sid: int) -> bool:
        hub.set_state("thinking")
        started = time.time()
        try:
            reply = Agent.run_turn(text)
        except Exception as exc:
            hub.toast(f"Agent error: {exc}")
            return sid == self.sid
        if sid != self.sid:
            return False
        hub.latency_ms = int((time.time() - started) * 1000)
        hub.emit({"type": "reply", "text": reply, "latency_ms": hub.latency_ms})
        hub.set_state("speaking")
        self._speak(reply)
        hub.add_log("text_to_speech", "VOICE", "reply spoken", "ok")
        return sid == self.sid

    def _speak(self, text: str) -> None:
        text = text[:1200]
        if sys.platform == "darwin":
            # `say` is reliable off the main thread and can be interrupted.
            self.say_proc = subprocess.Popen(["say", "-v", VOICE, text])
            if self.say_proc.wait() > 0:
                # Voice not installed on this Mac: use the system default.
                self.say_proc = subprocess.Popen(["say", text])
                self.say_proc.wait()
        else:
            speak(text)

    def _kill_speech(self) -> None:
        proc = self.say_proc
        if proc and proc.poll() is None:
            proc.terminate()


session = Session()


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    instrument_tools()
    set_confirm_handler(confirm)
    Memory.set_event_handler(on_memory_event)
    Agent.set_status_handler(session.announce)
    reminders.start(deliver=session.remind)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse(UI_FILE)


def handle(msg: dict) -> None:
    kind = msg.get("type")
    if kind == "toggle_voice":
        session.toggle()
    elif kind == "stop":
        session.stop()
    elif kind == "say":
        session.say(str(msg.get("text", "")))
    elif kind == "confirm_answer":
        item = hub.pending.get(str(msg.get("id")))
        if item:
            item[1]["ok"] = bool(msg.get("ok"))
            item[0].set()
    elif kind == "list_memories":
        hub.emit(memory_list())
    elif kind == "list_schedule":
        hub.emit(schedule_view(str(msg.get("start", ""))))
    elif kind == "delete_memory":
        # The user clicked delete themselves in the Memory view, so no popup.
        mid = str(msg.get("id", ""))
        if Memory.forget(mid):
            hub.add_log("forget", "MEMORY", mid, "deleted")
        hub.emit(memory_list())
    elif kind == "quit":
        session.stop()
        threading.Timer(0.3, lambda: os._exit(0)).start()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    if ws.headers.get("origin") not in ALLOWED_ORIGINS:
        await ws.close(code=1008)
        return
    await ws.accept()
    hub.clients.add(ws)
    await ws.send_json(hub.snapshot())
    # First window of this run: greet, then go straight to listening.
    if AUTO_LISTEN_ON_START and not session.greeted:
        session.greeted = True
        session.start_listening(greeting())
    try:
        while True:
            try:
                msg = await ws.receive_json()
            except (ValueError, KeyError):
                continue
            handle(msg)
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)