# Iris V0.8.1 (formerly Jarvis)

A local, voice-first assistant built around Ollama, with a holographic control-center UI, a personality, long-term memory, a clock, a schedule you can talk to (with spoken reminders and a Reminders tab for "don't forget" notes), a "Iris wake up" wake word, tasks with deadlines that plan themselves, filesystem tools, a controlled Python runner, Tavily web search, and a permanent log book.

## Project layout

```
Iris/                      <- the folder can keep its old name; the assistant is now called Iris
├── App.py                   <- main entry point: starts the server and opens the window
├── Server.py                <- local backend: bridges the UI to the agent over a WebSocket
├── Wake.py                  <- tiny always-on script: listens for "Iris wake up", delivers reminders while the app is closed
├── Agent.py                 <- the tool-calling loop and memory context (also runs in the terminal)
├── ToolSchemas.py           <- the tools the model may call and the function behind each
├── QuickPaths.py            <- common requests handled directly by rules, before the model
├── Config.py                <- settings in one place: name, how you are addressed, voices, model
├── Personality.py           <- the persona, example lines and system prompt
├── Strings.py               <- lines Iris says that do not come from the model (reminders, timers)
├── paths.py                 <- where code and personal data live (kept apart)
├── Llm.py                   <- the one place that calls Ollama chat (thinking switched off for speed)
├── requirements.txt         <- the Python packages the app needs
├── requirements-dev.txt     <- extra packages for the tests
├── .env                     <- your TAVILY_API_KEY (never committed)
├── Memory/
│   ├── __init__.py          <- memory facade: remember, recall, forget, context, end_session
│   ├── store.py             <- reads/writes memory_data/ (profile + memories)
│   ├── embeddings.py        <- Ollama embeddings + plain numpy cosine search
│   ├── history.py           <- this conversation (the model's last 10 turns + the full session, saved to disk)
│   └── summarizer.py        <- end-of-session summary
├── Schedule/                <- the schedule engine (was Tools/schedule.py, notes.py, timers.py)
│   ├── __init__.py          <- front door: everything other files import from here
│   ├── timeparse.py         <- times, dates, weekdays
│   ├── store.py             <- load / save schedule.json
│   ├── rules.py             <- busy, free, conflicts
│   ├── events.py            <- add, change, delete, place, clear a day
│   ├── planner.py           <- goals, plan_week, homework, days off
│   ├── tasks.py             <- tasks with deadlines: planning, priority, warnings before losing time
│   ├── alerts.py            <- which reminders are due
│   ├── view.py              <- the SCHEDULE tab's data
│   ├── notes.py             <- the REMINDERS tab
│   ├── timers.py            <- countdown timers
│   ├── parsers.py           <- plain speech -> tool arguments (no model needed)
│   └── permission.py        <- the Yes/No popup hook
├── Tools/
│   ├── __init__.py
│   ├── schedule_tools.py    <- the schedule functions the model calls (thin layer over Schedule/)
│   ├── filesystem.py        <- sandbox + list/read/create/edit/delete + permission hooks
│   ├── memory_tools.py      <- remember / recall / forget
│   ├── clock.py             <- current date/time, and times in other time zones
│   ├── reminders.py         <- the background thread that announces reminders
│   ├── system.py            <- everything that differs per operating system (voice, notifications, app check)
│   ├── python_runner.py
│   ├── web_search.py        <- Tavily search, with one quiet retry on a connection hiccup
│   ├── speech_to_text.py
│   └── text_to_speech.py
├── tests/                   <- automated tests (python tests/run_all.py); they never touch your data
├── ui/
│   └── index.html           <- the whole UI in one file (works offline)
├── memory_data/             <- your personal memory (never committed)
├── Schedule_data/           <- your schedule, notes, timers (never committed)
├── logs/                    <- the Log Book (never committed)
└── Test/                    <- the sandbox: the only folder Iris's file tools may touch
```

Run it from inside the project folder so the packages import correctly.

## What Iris can do

Everything from V0.5 (memory, personality, clock, search), plus:

- **Tasks with deadlines.** "I have a history essay due Friday, it'll take about 4 hours" or "I have a big chem test on Monday" (Iris asks how much time it needs). The work is split into sessions across your free time before the due date, shown in violet on the SCHEDULE tab with a TASKS list underneath (due date, priority, progress, time left and planned). See "Tasks with deadlines" below.
- **A wake word.** Run `Wake.py` and say "Iris wake up". It opens the app, which greets you and goes straight to listening, with a sphere that expands into the dashboard.
- **A schedule you can talk to.** Add, rename, move and delete events by voice ("add a physics session from 3 to 4 PM", "rename the 6 to 7 session to calculus"). The SCHEDULE tab shows the week (Sunday to Saturday) as a calendar with the hours down the left side.
- **Mandatory commitments are protected.** Classes, club and similar fixed events (and protected time such as sleep and dinner) can't be double-booked, and changing a fixed event asks permission first.
- **Goals and a week planner.** "Plan my week" fits goals (study, test prep) into free time. Homework has priority and starts a set time after your last commitment: "I have 3 hours of homework on Thursday" re-plans the week, moving other flexible events to another day by itself.
- **Days off.** "No school Thursday": school, club and gym are skipped that day.
- **A Reminders tab.** "Remind me to bring my charger tomorrow", "remind me at 7 PM to call dad", "don't let me forget the permission slip". Tick notes off by clicking or by voice ("cross off the charger"); "what do I need to remember?" reads them out. A note with a time is announced then, like any reminder (and respects quiet hours).
- **Reminders.** 15 minutes before an event, spoken and as a macOS notification, with quiet hours that hold spoken reminders back. They also work with the window closed (see below).

Earlier versions:

- **A personality.** Dry, quick-witted, a little sarcastic, and it drops the jokes when reporting errors. Edit `Personality.py` to tune it.
- **A clock.** The current date and time is in every prompt, so "what time is it?" just works. For other places Iris uses the `get_time` tool ("what time is it in Tokyo?"). It can also build schedules with real times and dates and save them to a file.
- **Spoken search status.** Iris says "One moment, sir. Searching for ..." before a web search. If the model says it is searching but forgets to call the tool, Iris runs the search for it, once per turn.
- **Short-term memory.** The last 10 turns, so follow-ups work.
- **Long-term memory in three layers:**
  1. **Profile** (`memory_data/profile.md`): core facts, in every prompt. Editable by hand. Capped at 500 words.
  2. **Memories** (`memory_data/memories.jsonl`): facts saved with "remember". While there are 12 or fewer, all go into every prompt. After that, the 4 closest matches by meaning.
  3. **Session summaries:** however a conversation ends (bye, STOP, standby, closing the app, even a crash), Iris saves a short summary of it.
- **Memory tools:** `remember`, `recall`, `forget`. Forgetting asks permission first. You can also read and delete memories in the MEMORY tab.

## Requirements

- A Mac (voice uses the built-in `say` command; tested on an M4 MacBook Air, 16 GB)
- Python 3.11 or newer (developed on 3.14 via pyenv)
- [Ollama](https://ollama.com) with these models:
  - `ollama pull qwen3.5:9b` (chat model)
  - `ollama pull nomic-embed-text` (memory search)
  - Run `ollama show qwen3.5:9b` and check that "tools" is listed under Capabilities. If not, use `qwen3:8b` and set `IRIS_MODEL=qwen3:8b` in `.env` (the old `JARVIS_MODEL` still works).
- A free [Tavily](https://tavily.com) API key for web search
- portaudio for the microphone: `brew install portaudio`
- For the wake word: `faster-whisper` (installed by `requirements.txt`; the tiny speech model downloads once on first run)
- Internet (speech recognition uses Google Web Speech, web search uses Tavily)
- A working microphone and speakers

Python packages (all in `requirements.txt`): ollama, tavily-python, python-dotenv, SpeechRecognition, pyaudio, pyttsx3, fastapi, uvicorn[standard], pywebview, numpy, faster-whisper.

## Setup (from scratch)

1. Get the code:
   ```bash
   git clone https://github.com/Helloz33/Jarvis.git ~/Jarvis
   cd ~/Jarvis
   ```
2. Install Ollama, start it (the app, or `ollama serve`), then pull the models:
   ```bash
   ollama pull qwen3.5:9b
   ollama pull nomic-embed-text
   ```
3. Install the microphone library **before** the next step, or pyaudio won't build:
   ```bash
   brew install portaudio
   ```
4. Install the Python packages:
   ```bash
   python -m pip install -r requirements.txt
   ```
5. Create your `.env` from the template and put your real key in it:
   ```bash
   cp .env.example .env
   open -e .env
   ```
   Optional lines: `IRIS_MODEL=qwen3:8b` and `JARVIS_EMBED_MODEL=nomic-embed-text`
6. Make sure `.gitignore` contains these lines (memory holds personal facts, never upload it):
   ```
   .env
   logs/
   memory_data/
   Schedule_data/
   models/
   ```
7. The first run, macOS asks for microphone permission. Allow it (System Settings > Privacy & Security > Microphone) for your terminal or VS Code.

## Run Iris

From inside `~/Jarvis/`:

```bash
python App.py
```

If the native window can't start on your Python version, Iris opens the same page in your browser (http://127.0.0.1:8765). Terminal mode still works: `python Agent.py`.

Optional shortcut: add this to `~/.zshrc`, run `source ~/.zshrc`, then type `jarvis` from anywhere:

```bash
jarvis() { cd ~/Jarvis && python App.py; }
```

## Wake word and reminders (optional)

`Wake.py` is a tiny script that listens for "Iris wake up" with a small local speech model, then opens the app. While the app is closed it also delivers schedule reminders (a notification and a spoken line). A few close mishearings ("Irish wake up") count too.

Try it first: `python Wake.py`, then say "Iris wake up". macOS asks for microphone access the first time.

To keep it running in the background, create `~/Library/LaunchAgents/com.jarvis.wake.plist` (replace both paths with your own, using full absolute paths) and load it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jarvis.wake</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOU/.pyenv/versions/3.14.8/bin/python</string>
    <string>/Users/YOU/Jarvis/Wake.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.jarvis.wake.plist
```

**Updating from V0.8:** the script was renamed from `Wake_Jarvis.py` to `Wake.py`. Change that line in your plist, then reload it:

```bash
launchctl unload ~/Library/LaunchAgents/com.jarvis.wake.plist
launchctl load ~/Library/LaunchAgents/com.jarvis.wake.plist
```

## Your schedule

Your schedule is one file, `Schedule_data/schedule.json`, created on first run and never committed. Edit it by hand or just tell Iris. Handy things to say:

- "What's my schedule for today?" / "How is my schedule looking?"
- "Add an hour of physics at 4 PM." / "Set a study session from 6 to 7 PM."
- "Rename the 6 to 7 PM session to calculus."
- "Set my homework to 90 minutes." / "I have 3 hours of homework on Thursday."
- "No school on Friday." / "Plan my week."

### Tasks with deadlines

- **Add:** "I have a history essay due Friday, it'll take about 4 hours", "chem lab report due next Monday, 3 hours, it's worth 30% of my grade", "I have a big chem test on Friday" (Iris asks how long; answer "about 3 hours").
- **Progress:** "I did 45 minutes of the essay", "I finished the history essay" / "the essay is done".
- **Ask:** "What's due this week?", "How much is left on the essay?"
- **Change:** "Make the essay high priority", or ask Iris to change the due date or estimate.

How it plans:

- The time left is split into sessions (30 to 90 minutes, normally 60) across free time before the due date, at most 3 hours of task work a day. "Due Friday" means finished before Friday; give a time ("due Friday at 9 AM") to allow work on the day itself.
- It aims to finish a day early. If that is impossible it uses the last day and says so; if even that is not enough it says how much is missing.
- **Priority** is the higher of what you said (high for "important", "big test", "worth 30%"...; low for "not important", "no rush") and how urgent the task has become: due within 2 days, or the work left is large compared with your free time, counts as high (due within 4 days, at least normal). Iris says once when urgency raises a task.
- A high-priority task that does not fit may move automatically planned goal sessions (e.g. physics self-study) to another time, never your own appointments, fixed events or homework.
- **Before anything takes time from a task** (deleting or moving a session, clearing a day, adding an event on top of a session) Iris checks the deadline. If it still fits, she just does it and says where the time went. If it would only fit by cramming, or not at all, she asks first. High-priority tasks always ask. Saying no never makes it permanent.
- A session that passes without you reporting progress counts as missed, and its time is planned again (checked every 10 minutes). Reported progress removes surplus sessions.
- Settings (optional) go under `settings.tasks` in `schedule.json`: `daily_cap_minutes` (180), `min_session_minutes` (30), `max_session_minutes` (90), `buffer_days` ({"high": 1, "normal": 1, "low": 0}), `urgent_days` (2), `soon_days` (4), `behind_ratio` (0.6).

Reminders come 15 minutes ahead. Events with `"remind": false` (e.g. school) never remind. Settings live under `settings.reminders` in the schedule file: `lead_minutes` and `quiet_until` (a time per weekday, e.g. `{"MO": "18:00"}`). Spoken reminders are held until quiet hours end; an event inside quiet hours gets a silent notification.

## Using Iris

- Click the core to start listening. Say "bye" (or press STOP) to end.
- Approve or deny any edit, delete, forget or permanent-memory popup with YES or NO. Esc counts as NO.
- Open the LOG BOOK to see everything Iris has done. Filter by FILES, RUN, WEB, MEMORY or VOICE.
- Open the MEMORY tab to read your profile and memories, and delete any (click the X twice).
- No microphone? Open http://127.0.0.1:8765/#dev for a text box.
- STOP (or tapping the core) puts Iris in STANDBY; the conversation is saved to memory after 90 seconds there.

**First thing to do:** tell Iris about yourself, e.g. "Remember that I live in Baden, Pennsylvania." Then check the MEMORY tab. If something doesn't save, type facts into `memory_data/profile.md` by hand, one per line starting with `- `.

## Test it

1. "Remember that my favourite colour is teal." -> MEMORY entry in the Log Book
2. "What's my favourite colour?" -> answers teal
3. "What time is it?" -> answers from the clock, no search
4. "What time is it in Tokyo?" -> uses `get_time`
5. "Search the web for the Python asyncio docs." -> says it is searching, then answers
6. Say "bye", start again, ask "What did we do last time?" -> uses the saved summary
7. "Forget that my favourite colour is teal." -> popup with the memory text
8. "Create a file hello2.py that prints hi." -> should sound like Iris
9. Check the MEMORY tab: the colour memory is gone after step 7.

## Troubleshooting

- **"model not installed":** `ollama pull qwen3.5:9b` (or set `IRIS_MODEL` in `.env`).
- **ModuleNotFoundError: No module named 'Tools.schedule'** (or notes/timers): an old file is still importing them. Make sure you replaced every file from V0.8.1 and deleted `Tools/schedule.py`, `Tools/notes.py` and `Tools/timers.py`.
- **The voice is not the one you expected:** Iris uses the first voice in `Config.VOICES_MAC` that is installed. Download Serena (Premium) in System Settings > Accessibility > Spoken Content > System Voice > Manage Voices, or put a voice you have first in the list.
- **`ollama pull` says "blocked redirect to a different host":** your network is intercepting the download. Try a phone hotspot or another network.
- **"embedding model ... is not installed":** `ollama pull nomic-embed-text`. Until then memory uses keyword matching.
- **pyaudio fails to install:** you skipped `brew install portaudio`.
- **ImportError from Tools or Memory:** save every file (unsaved VS Code tabs are empty on disk) and run from inside the Jarvis folder.
- **Iris ignores something it should know:** a 9B model sometimes does. Check the fact is in the MEMORY tab and say it again plainly.
- **Searches take 30+ seconds:** normal for a local 9B model reading results.

## How memory works

Every turn, `Agent.run_turn` builds the prompt from: persona + rules, the current date and time, your profile, your memories (all while there are 12 or fewer, otherwise the 4 closest matches), and the last 10 turns. Matching uses embeddings and plain numpy cosine similarity. No vector database is needed at this size. Without the embedding model, Iris falls back to keyword matching.

## Security model

Everything from V0.4 still applies: the `Test/` sandbox, approval for edits and deletes, 127.0.0.1-only server, WebSocket origin check.

New in V0.5:

- Forgetting a memory asks first. Saving to the permanent profile asks first.
- Outside content can't write memory silently. If a turn has read a web search, a file, or script output, `remember` asks your permission first. This blocks memory poisoning ("remember that...").
- Recalled memories are given to the model labelled as data, not instructions.
- `memory_data/` is local only. Embeddings and summaries are made by your local Ollama.

## Tuning

- `Config.py`: NAME (Iris), USER_ADDRESS ("sir", or "" for none), VOICES_MAC / VOICES_WINDOWS (the first one installed is used), MODEL
- `Personality.py`: persona text and examples
- `Strings.py`: the fixed spoken lines (reminders, timers)
- `Memory/history.py`: MAX_TURNS (10), MAX_FULL_TURNS (120, kept for the summary)
- `Server.py`: STANDBY_SAVE_SECONDS (90), IDLE_SAVE_MINUTES (10)
- `Memory/__init__.py`: RECALL_K (4), RECALL_THRESHOLD (0.4), INCLUDE_ALL_BELOW (12)
- `Memory/store.py`: PROFILE_WORD_CAP (500), MAX_FACT_CHARS (300)
- `Agent.py`: MAX_TOOL_CALLS
- `QuickPaths.py`: PERSONA_ON_WRITES (set False for speed)
- `Server.py`: TASK_CHECK_MINUTES (10)
- `paths.py` / `IRIS_DATA_DIR` in `.env`: move your personal data to another folder
- `Llm.py`: THINK (True lets reasoning models think before answering)

## What's new in V0.8.1

- **Renamed to Iris**, with a female voice (Serena, falling back to Kate or Samantha, then the system voice). The name lives in one place, `Config.py`: the persona, the window, notifications, the Log Book and the wake phrase ("Iris wake up") all follow it.
- **Tasks with deadlines**, with priority (what you say plus urgency as the due date comes closer), automatic planning before the due date, warnings before anything takes time from a task, progress and missed-session re-planning. See "Tasks with deadlines" above.
- **Restructure (no behaviour change):** the 1,400-line `Tools/schedule.py` became the `Schedule/` package (with notes and timers moved in), `Agent.py` was split into `Agent.py`, `ToolSchemas.py` and `QuickPaths.py`, and `paths.py` keeps code and personal data apart (groundwork for the V1.0 app). A test replays 472 V0.8 results and checks they are unchanged.
- **Plain-language tool errors:** a failed web search is retried once quietly (connection hiccups such as the earlier SSL error), then explained in plain words ("could not reach the search service"), and the model is told not to keep retrying.
- **"Sir" is one setting** (`Config.USER_ADDRESS`): reminders, notes and timers no longer have it written into them. A Settings switch for it comes in V1.0.
- **Wake.py** (was `Wake_Jarvis.py`) now really delivers reminders while the app is closed, as the README always said.
- **Tests** in `tests/` (`python tests/run_all.py`), and `requirements-dev.txt` for the packages they need. They are in `tests/`, not `Test/`, because `Test/` is the sandbox the assistant's file tools can read and write.

## What's new in V0.8

- **Memory is saved however a conversation ends (bug fix).** Before, the end-of-session summary only happened when you said "bye", so STOP, closing the window or a crash lost it. Now:
  - the conversation is written to `memory_data/session_current.json` after every turn;
  - it is summarized when you say bye, after 90 seconds in STANDBY (STOP, tapping the core, SHUT DOWN, or after a typed message), after 10 minutes of listening with nothing said, and when you close the app;
  - a conversation the app never got to save (force quit, crash, power cut) is summarized the next time Jarvis starts;
  - if the summary fails (for example Ollama is not running), the conversation is kept and tried again later;
  - the summary now covers the whole conversation, not just the last 10 turns.
- **Timers:** "set a 25 minute timer", "set a pasta timer for 10 minutes", "how much time is left?", "cancel the pasta timer", "cancel all timers". When one ends Jarvis says so and shows a notification (even in quiet hours). Timers survive a restart, and one that ended while the app was closed is reported when it opens.

## What's new in V0.7

- **Platform layer (`Tools/system.py`):** the macOS-only code (the `say` voice, notifications, the "is the app running?" check) now lives in one file. Windows and Linux versions are written, but they have **not been tested on a real machine yet**, so treat them as experimental. macOS behaves exactly as before.
- Nothing else changes for you. This release is groundwork for the later installer and a possible cloud/phone version.

## What's new in V0.6.2

- **REMINDERS tab and voice notes:** "remind me to ...", "don't let me forget ...", "cross off ...", "what do I need to remember?". Timed notes are announced when due (quiet hours respected). Notes live in `Schedule_data/notes.json`.
- **Place it for me:** "add 2 hours of test prep, one for math and one for chem, place it how you see fit" or "add a 1-hour session after my club called physics prep". Jarvis picks free times (`place_event`).
- **Clear a day:** "remove the homework and physics stuff and test prep on Monday and Tuesday" or "remove everything on Monday". Those goals stay off those days when the week is re-planned (`clear_day`).
- **Days off by voice, and a declined popup is no longer final:** "mark today and tomorrow as days off" works directly, and saying "do it" after pressing Deny asks again. Undoing one day of a range keeps the rest.
- Fix: the SCHEDULE tab icon was missing; the tab row now wraps on narrow windows.

## What's new in V0.6

- Wake word ("Jarvis wake up") with an always-on script, and a sphere wake-up animation
- Jarvis greets you and goes straight to listening
- Schedule system: events, protected time, conflict checks with free-time suggestions, goals, homework priority, days off, a week planner
- SCHEDULE tab: a Sunday-to-Saturday calendar with hours down the left side, live updates
- Spoken and silent reminders with quiet hours (`Tools/reminders.py`)
- Plain "add / rename / homework" requests are handled directly (more reliable than leaving it to the model), and Jarvis no longer claims it changed the schedule unless it did
- Fix: the Log Book is no longer hidden under the wake-up overlay

## What's new in V0.5

- Long-term memory (profile, retrievable memories, session summaries) and remember/recall/forget tools
- Short-term conversation history
- A personality in its own file, with a British macOS voice
- A clock: date/time in every prompt, plus `get_time` for other time zones
- Spoken "searching..." status, and an automatic fallback if the model forgets to call `web_search`
- Model upgraded from qwen2.5-coder:7b to qwen3.5:9b (configurable)
- The UI is now a single self-contained `index.html`
- MEMORY category in the Log Book, a Memory Bank tab, and a "wants to forget" popup
- Generalised permission code (`ask_permission`) so any tool can ask first

## Known limitations

- Check the model tag and tool support with `ollama show`.
- The first reply after a model switch is slow while Ollama loads it.
- With little data, the keyword fallback can miss paraphrases; install `nomic-embed-text`.
- No weather tool (tried and removed). Ask for the weather and Iris searches the web.
- The SCHEDULE tab is view-only; change things by talking to Iris or editing `schedule.json`.
- The direct paths (reminders, timers, tasks...) understand English only; other phrasings go to the model.
- Task estimates are only as good as your guesses: report progress so the plan stays honest.
- Speech recognition (Google) sometimes mishears times; say "from 6:10 to 6:40 PM" in one go.
- The CALL button is still a placeholder.
- Windows and Linux support (`Tools/system.py`) is untested; macOS is the supported platform.

## Development notes

Check `git status` before every commit: `.env`, `logs/`, `memory_data/`, `Schedule_data/` and `models/` must not appear.

```bash
python tests/run_all.py
git add -A
git commit -m "V0.8.1: Schedule package, rename to Iris, tasks with deadlines"
git push
git tag -a v0.8.1 -m "Iris V0.8.1 - restructure, rename, tasks with deadlines"
git push origin v0.8.1
```

**Current version:** V0.8.1, Schedule package, rename to Iris, tasks with deadlines