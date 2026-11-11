"""Backend: serves the HUD and bridges it to the agent.

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
from fastapi.responses import HTMLResponse

import Agent
import Memory
import Config
from Personality import AUTO_LISTEN_ON_START, greeting
import paths
from Schedule import notes as notes_tools
from Schedule import timers, week_view
from Tools import SANDBOX, listen, notes_view, reminders, set_confirm_handler, speak
from Tools import system

PORT = 8765
ITERATION = "V0.8.1"
ROOT = Path(__file__).resolve().parent
UI_FILE = ROOT / "ui" / "index.html"
EXIT_WORDS = {"exit", "quit", "bye"}
# The conversation is saved to long-term memory however it ends (see Memory.end_session):
STANDBY_SAVE_SECONDS = 90   # in STANDBY (STOP, tapping the core, SHUT DOWN, after a typed turn) for this long: save
IDLE_SAVE_MINUTES = 10      # still listening but nothing said for this long: save
CONFIRM_TIMEOUT_SECONDS = 120
# Only pages served by this app may open the WebSocket (stops other websites
# open in your browser from talking to the assistant).
ALLOWED_ORIGINS = {f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"}

CATEGORY = {
    "list_files": "FILES", "read_file": "FILES", "create_file": "FILES",
    "edit_file": "FILES", "delete_file": "FILES",
    "run_python": "RUN", "web_search": "WEB", "get_time": "RUN",
    "remember": "MEMORY", "recall": "MEMORY", "forget": "MEMORY",
    "list_schedule": "RUN", "add_event": "RUN", "place_event": "RUN", "clear_day": "RUN", "add_note": "RUN", "set_timer": "RUN", "cancel_timer": "RUN", "list_timers": "RUN", "list_notes": "RUN", "complete_note": "RUN", "clear_notes": "RUN", "update_event": "RUN",
    "delete_event": "RUN", "set_goal": "RUN", "set_day_off": "RUN", "adjust_homework": "RUN", "plan_week": "RUN",
    "add_task": "RUN", "list_tasks": "RUN", "update_task": "RUN", "log_task_progress": "RUN", "delete_task": "RUN",
}
TASK_CHECK_MINUTES = 10     # how often task plans are brought up to date (missed sessions are re-planned)


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
    if name == "place_event":
        return str(kwargs.get("titles") or kwargs.get("title", ""))
    if name == "add_note":
        return str(kwargs.get("text", ""))
    if name == "set_timer":
        mins = kwargs.get("minutes", 0) or 0
        return f"{kwargs.get('label') or 'timer'} ({mins:g} min)" if isinstance(mins, (int, float)) else str(kwargs.get("label", "timer"))
    if name in ("add_task", "update_task", "log_task_progress", "delete_task"):
        return str(kwargs.get("title") or kwargs.get("task", ""))
    if name == "list_tasks":
        return "tasks"
    if name in ("cancel_timer", "list_timers"):
        return str(kwargs.get("timer", "")) or "timers"
    if name == "complete_note":
        return str(kwargs.get("note", ""))
    if name in ("list_notes", "clear_notes"):
        return "reminders"
    if name in ("add_event", "set_goal"):
        return str(kwargs.get("title", ""))
    if name == "adjust_homework":
        return f"{kwargs.get('minutes', '')} min {kwargs.get('date', 'today')}"
    if name in ("set_day_off", "clear_day"):
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
        self.idle_since = time.time()     # when STANDBY began (used to save the conversation)
        self.latency_ms: int | None = None
        self.counts = {"FILES": 0, "RUN": 0, "WEB": 0, "MEMORY": 0, "VOICE": 0}
        self.logs: list[dict] = []
        self.pending: dict[str, tuple[threading.Event, dict]] = {}
        self._lock = threading.Lock()
        self._load_logs()

    def _load_logs(self) -> None:
        log_file = paths.LOG_DIR / "logbook.jsonl"
        if not log_file.exists():
            return
        try:
            for line in log_file.read_text(encoding="utf-8").splitlines()[-500:]:
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
            "name": Config.NAME,
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
        loop = self.loop
        if loop is None or loop.is_closed():
            return                       # the app is shutting down: nobody is listening any more
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(event), loop)
        except RuntimeError:
            pass

    async def _broadcast(self, event: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(event)
            except Exception:
                self.clients.discard(ws)

    def set_state(self, state: str) -> None:
        if state == "idle" and self.state != "idle":
            self.idle_since = time.time()
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
                paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
                with (paths.LOG_DIR / "logbook.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError:
                pass
        self.emit({
            "type": "log", "entry": entry, "calls": len(self.logs),
            "counts": self.counts, "files": self.file_count(),
            "memory": Memory.stats(),
        })


hub = Hub()


NOTE_TOOLS = {"add_note", "list_notes", "complete_note", "clear_notes"}
SCHEDULE_TOOLS = {"add_event", "place_event", "clear_day", "update_event", "delete_event", "set_goal", "set_day_off",
                  "adjust_homework", "plan_week", "add_task", "update_task", "log_task_progress", "delete_task"}


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
            if name in NOTE_TOOLS:
                hub.emit(notes_view())      # ... and the REMINDERS tab
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
        "recover": ("session_summary", "ok"),
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

    def save_memory(self, reason: str, wait: bool = False) -> bool:
        """End the conversation and summarize it into long-term memory."""
        if not len(Memory.history):
            return False
        started = Memory.end_session(Agent.MODEL, on_done=lambda: hub.emit(memory_list()), wait=wait, timeout=25)
        if started:
            hub.add_log("end_session", "MEMORY", f"conversation saved ({reason})", "ok")
        return started

    def watch_session(self) -> None:
        """Background check: save the conversation after STOP or when it has gone quiet."""
        while True:
            time.sleep(15)
            try:
                self.check_session()
            except Exception:
                pass

    def check_session(self, now: float | None = None) -> str:
        """Save the conversation once the assistant has been in STANDBY for 90 seconds (however it got
        there: STOP, tapping the core, SHUT DOWN, the end of a typed turn), or after 10 minutes
        of listening with nothing said."""
        if not len(Memory.history):
            return ""
        now = now or time.time()
        if hub.state == "idle":
            if now - max(hub.idle_since, Memory.history.last) >= STANDBY_SAVE_SECONDS:
                self.save_memory("standby")
                return "standby"
        elif hub.state == "listening" and now - Memory.history.last >= IDLE_SAVE_MINUTES * 60:
            self.save_memory("idle")
            return "idle"
        return ""

    def watch_tasks(self) -> None:
        """Keep task plans up to date: a session that passed without progress counts as missed, and
        its time is planned again; urgency rises as due dates come closer."""
        import Schedule
        while True:
            try:
                result = Schedule.plan_tasks()
                if result:
                    hub.add_log("plan_tasks", "RUN", result[:160], "ok")
                    hub.emit(schedule_view())
                    for line in [l for l in result.split(". ") if "treating it as" in l]:
                        hub.toast(line.rstrip(".") + ".")
            except Exception as exc:
                print(f"[tasks] {exc}")
            time.sleep(TASK_CHECK_MINUTES * 60)

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

    def timer_done(self, text: str) -> None:
        """A timer ended (called from its timer thread). Timers always speak, even in quiet hours."""
        hub.add_log("timer", "RUN", text, "done")
        hub.toast(text)
        reminders.notify(text)
        with self.lock:
            self.reminder_lines.append(text)
        if hub.state == "idle":
            self.say_reminders()

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
                    self.save_memory("said goodbye")
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
        # The system layer talks through the OS voice (interruptible); pyttsx3 is the last resort.
        spoken = system.speak(text, Config.voice(), on_start=lambda p: setattr(self, "say_proc", p))
        if not spoken:
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
    timers.start(deliver=session.timer_done)
    # A conversation the app never got to save (crash, force quit, closed window) is saved now.
    threading.Thread(target=lambda: Memory.recover_session(Agent.MODEL, on_done=lambda: hub.emit(memory_list())),
                     daemon=True).start()
    threading.Thread(target=session.watch_session, daemon=True, name="session-watch").start()
    threading.Thread(target=session.watch_tasks, daemon=True, name="task-watch").start()
    yield
    session.save_memory("app closed", wait=True)


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    # The page says the assistant's name wherever it has __NAME__ / __NAME_UP__ / __NAME_DOTS__ (I.R.I.S).
    html = UI_FILE.read_text(encoding="utf-8")
    dots = ".".join(Config.NAME.upper()) + ("" if len(Config.NAME) > 1 else "")
    return HTMLResponse(html.replace("__NAME_DOTS__", dots).replace("__NAME_UP__", Config.NAME.upper())
                        .replace("__NAME__", Config.NAME))


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
    elif kind == "list_notes":
        hub.emit(notes_view())
    elif kind in ("toggle_note", "delete_note"):
        # The user clicked it themselves in the Reminders tab, so no popup.
        nid = str(msg.get("id", ""))
        if kind == "toggle_note" and notes_tools.toggle_note(nid):
            hub.add_log("complete_note", "RUN", nid, "ok")
        elif kind == "delete_note" and notes_tools.delete_note(nid):
            hub.add_log("complete_note", "RUN", nid, "deleted")
        hub.emit(notes_view())
    elif kind == "delete_memory":
        # The user clicked delete themselves in the Memory view, so no popup.
        mid = str(msg.get("id", ""))
        if Memory.forget(mid):
            hub.add_log("forget", "MEMORY", mid, "deleted")
        hub.emit(memory_list())
    elif kind == "quit":
        session.stop()

        def finish():
            if len(Memory.history):
                hub.toast("Saving this conversation to memory...")
                session.save_memory("app closed", wait=True)   # anything unfinished is redone next start
            os._exit(0)

        threading.Thread(target=finish, daemon=True).start()


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