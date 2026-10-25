# Jarvis V0.6

A local, voice-first assistant built around Ollama, with a holographic control-center UI, a personality, long-term memory, a clock, a schedule you can talk to (with spoken reminders), a "Jarvis wake up" wake word, filesystem tools, a controlled Python runner, Tavily web search, and a permanent log book.

## Project layout

```
Jarvis/
├── App.py                   <- main entry point: starts the server and opens the Jarvis window
├── Server.py                <- local backend: bridges the UI to the agent over a WebSocket
├── Wake_Jarvis.py           <- tiny always-on script: listens for "Jarvis wake up" and opens the app
├── Agent.py                 <- tool schemas, the tool-calling loop, memory context (also runs in the terminal)
├── Personality.py           <- Jarvis's persona, example lines, system prompt, voice name
├── Llm.py                   <- the one place that calls Ollama chat (thinking switched off for speed)
├── requirements.txt         <- every Python package Jarvis needs
├── .env                     <- your TAVILY_API_KEY (never committed)
├── .env.example             <- safe template for .env
├── Memory/
│   ├── __init__.py          <- memory facade: remember, recall, forget, context, end_session
│   ├── store.py             <- reads/writes memory_data/ (profile + memories)
│   ├── embeddings.py        <- Ollama embeddings + plain numpy cosine search
│   ├── history.py           <- short-term memory: the last 10 turns
│   └── summarizer.py        <- end-of-session summary
├── memory_data/             <- your personal memory (created automatically, never committed)
│   ├── profile.md
│   └── memories.jsonl
├── Schedule_data/           <- your personal schedule (created automatically, never committed)
│   └── schedule.json
├── ui/
│   └── index.html           <- the whole UI in one file (works offline)
├── logs/
│   └── logbook.jsonl        <- one line per tool call (never committed)
├── Tools/
│   ├── __init__.py
│   ├── filesystem.py        <- sandbox + list/read/create/edit/delete + permission hooks
│   ├── memory_tools.py      <- remember / recall / forget
│   ├── clock.py             <- current date/time, and times in other time zones
│   ├── schedule.py          <- the schedule: events, goals, homework, days off, week planner
│   ├── reminders.py         <- spoken and silent reminders ("Sir, we have ... scheduled for ...")
│   ├── python_runner.py
│   ├── web_search.py
│   ├── speech_to_text.py
│   └── text_to_speech.py
└── Test/
    └── hello.py
```

Run Jarvis from inside the `Jarvis/` directory so the packages import correctly.

## What Jarvis can do

Everything from V0.5 (memory, personality, clock, search), plus:

- **A wake word.** Run `Wake_Jarvis.py` and say "Jarvis wake up". It opens the app, which greets you and goes straight to listening, with a sphere that expands into the dashboard.
- **A schedule you can talk to.** Add, rename, move and delete events by voice ("add a physics session from 3 to 4 PM", "rename the 6 to 7 session to calculus"). The SCHEDULE tab shows the week (Sunday to Saturday) as a calendar with the hours down the left side.
- **Mandatory commitments are protected.** Classes, club and similar fixed events (and protected time such as sleep and dinner) can't be double-booked, and changing a fixed event asks permission first.
- **Goals and a week planner.** "Plan my week" fits goals (study, test prep) into free time. Homework has priority and starts a set time after your last commitment: "I have 3 hours of homework on Thursday" re-plans the week, moving other flexible events to another day by itself.
- **Days off.** "No school Thursday": school, club and gym are skipped that day.
- **Reminders.** 15 minutes before an event, spoken and as a macOS notification, with quiet hours that hold spoken reminders back. They also work with the window closed (see below).

Earlier versions:

- **A personality.** Dry, quick-witted, a little sarcastic, and it drops the jokes when reporting errors. Edit `Personality.py` to tune it.
- **A clock.** The current date and time is in every prompt, so "what time is it?" just works. For other places Jarvis uses the `get_time` tool ("what time is it in Tokyo?"). It can also build schedules with real times and dates and save them to a file.
- **Spoken search status.** Jarvis says "One moment, sir. Searching for ..." before a web search. If the model says it is searching but forgets to call the tool, Jarvis runs the search for it, once per turn.
- **Short-term memory.** The last 10 turns, so follow-ups work.
- **Long-term memory in three layers:**
  1. **Profile** (`memory_data/profile.md`): core facts, in every prompt. Editable by hand. Capped at 500 words.
  2. **Memories** (`memory_data/memories.jsonl`): facts saved with "remember". While there are 12 or fewer, all go into every prompt. After that, the 4 closest matches by meaning.
  3. **Session summaries:** when you say "bye", Jarvis saves a short summary of the chat.
- **Memory tools:** `remember`, `recall`, `forget`. Forgetting asks permission first. You can also read and delete memories in the MEMORY tab.

## Requirements

- A Mac (voice uses the built-in `say` command; tested on an M4 MacBook Air, 16 GB)
- Python 3.11 or newer (developed on 3.14 via pyenv)
- [Ollama](https://ollama.com) with these models:
  - `ollama pull qwen3.5:9b` (chat model)
  - `ollama pull nomic-embed-text` (memory search)
  - Run `ollama show qwen3.5:9b` and check that "tools" is listed under Capabilities. If not, use `qwen3:8b` and set `JARVIS_MODEL=qwen3:8b` in `.env`.
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
   Optional lines: `JARVIS_MODEL=qwen3:8b` and `JARVIS_EMBED_MODEL=nomic-embed-text`
6. Make sure `.gitignore` contains these lines (memory holds personal facts, never upload it):
   ```
   .env
   logs/
   memory_data/
   Schedule_data/
   models/
   ```
7. The first run, macOS asks for microphone permission. Allow it (System Settings > Privacy & Security > Microphone) for your terminal or VS Code.

## Run Jarvis

From inside `~/Jarvis/`:

```bash
python App.py
```

If the native window can't start on your Python version, Jarvis opens the same page in your browser (http://127.0.0.1:8765). Terminal mode still works: `python Agent.py`.

Optional shortcut: add this to `~/.zshrc`, run `source ~/.zshrc`, then type `jarvis` from anywhere:

```bash
jarvis() { cd ~/Jarvis && python App.py; }
```

## Wake word and reminders (optional)

`Wake_Jarvis.py` is a tiny script that listens for "Jarvis wake up" with a small local speech model, then opens Jarvis. It also delivers schedule reminders when the app is closed.

Try it first: `python Wake_Jarvis.py`, then say "Jarvis wake up". macOS asks for microphone access the first time.

To keep it running in the background, create `~/Library/LaunchAgents/com.jarvis.wake.plist` (replace both paths with your own, using full absolute paths) and load it:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jarvis.wake</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOU/.pyenv/versions/3.14.8/bin/python</string>
    <string>/Users/YOU/Jarvis/Wake_Jarvis.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.jarvis.wake.plist
```

## Your schedule

Your schedule is one file, `Schedule_data/schedule.json`, created on first run and never committed. Edit it by hand or just tell Jarvis. Handy things to say:

- "What's my schedule for today?" / "How is my schedule looking?"
- "Add an hour of physics at 4 PM." / "Set a study session from 6 to 7 PM."
- "Rename the 6 to 7 PM session to calculus."
- "Set my homework to 90 minutes." / "I have 3 hours of homework on Thursday."
- "No school on Friday." / "Plan my week."

Reminders come 15 minutes ahead. Events with `"remind": false` (e.g. school) never remind. Settings live under `settings.reminders` in the schedule file: `lead_minutes` and `quiet_until` (a time per weekday, e.g. `{"MO": "18:00"}`). Spoken reminders are held until quiet hours end; an event inside quiet hours gets a silent notification.

## Using Jarvis

- Click the core to start listening. Say "bye" (or press STOP) to end.
- Approve or deny any edit, delete, forget or permanent-memory popup with YES or NO. Esc counts as NO.
- Open the LOG BOOK to see everything Jarvis has done. Filter by FILES, RUN, WEB, MEMORY or VOICE.
- Open the MEMORY tab to read your profile and memories, and delete any (click the X twice).
- No microphone? Open http://127.0.0.1:8765/#dev for a text box.

**First thing to do:** tell Jarvis about yourself, e.g. "Remember that I live in Baden, Pennsylvania." Then check the MEMORY tab. If something doesn't save, type facts into `memory_data/profile.md` by hand, one per line starting with `- `.

## Test it

1. "Remember that my favourite colour is teal." -> MEMORY entry in the Log Book
2. "What's my favourite colour?" -> answers teal
3. "What time is it?" -> answers from the clock, no search
4. "What time is it in Tokyo?" -> uses `get_time`
5. "Search the web for the Python asyncio docs." -> says it is searching, then answers
6. Say "bye", start again, ask "What did we do last time?" -> uses the saved summary
7. "Forget that my favourite colour is teal." -> popup with the memory text
8. "Create a file hello2.py that prints hi." -> should sound like Jarvis
9. Check the MEMORY tab: the colour memory is gone after step 7.

## Troubleshooting

- **"model not installed":** `ollama pull qwen3.5:9b` (or set `JARVIS_MODEL` in `.env`).
- **`ollama pull` says "blocked redirect to a different host":** your network is intercepting the download. Try a phone hotspot or another network.
- **"embedding model ... is not installed":** `ollama pull nomic-embed-text`. Until then memory uses keyword matching.
- **pyaudio fails to install:** you skipped `brew install portaudio`.
- **ImportError from Tools or Memory:** save every file (unsaved VS Code tabs are empty on disk) and run from inside the Jarvis folder.
- **Jarvis ignores something it should know:** a 9B model sometimes does. Check the fact is in the MEMORY tab and say it again plainly.
- **Searches take 30+ seconds:** normal for a local 9B model reading results.

## How memory works

Every turn, `Agent.run_turn` builds the prompt from: persona + rules, the current date and time, your profile, your memories (all while there are 12 or fewer, otherwise the 4 closest matches), and the last 10 turns. Matching uses embeddings and plain numpy cosine similarity. No vector database is needed at this size. Without the embedding model, Jarvis falls back to keyword matching.

## Security model

Everything from V0.4 still applies: the `Test/` sandbox, approval for edits and deletes, 127.0.0.1-only server, WebSocket origin check.

New in V0.5:

- Forgetting a memory asks first. Saving to the permanent profile asks first.
- Outside content can't write memory silently. If a turn has read a web search, a file, or script output, `remember` asks your permission first. This blocks memory poisoning ("remember that...").
- Recalled memories are given to the model labelled as data, not instructions.
- `memory_data/` is local only. Embeddings and summaries are made by your local Ollama.

## Tuning

- `Personality.py`: USER_ADDRESS, VOICE, persona text and examples
- `Memory/history.py`: MAX_TURNS (10)
- `Memory/__init__.py`: RECALL_K (4), RECALL_THRESHOLD (0.4), INCLUDE_ALL_BELOW (12)
- `Memory/store.py`: PROFILE_WORD_CAP (500), MAX_FACT_CHARS (300)
- `Agent.py`: MODEL, MAX_TOOL_CALLS, PERSONA_ON_WRITES (set False for speed)
- `Llm.py`: THINK (True lets reasoning models think before answering)

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
- Session summaries only happen when you say "bye" (not on STOP or closing the window).
- The first reply after a model switch is slow while Ollama loads it.
- With little data, the keyword fallback can miss paraphrases; install `nomic-embed-text`.
- No weather tool (tried and removed). Ask for the weather and Jarvis searches the web.
- The SCHEDULE tab is view-only; change things by talking to Jarvis or editing `schedule.json`.
- Speech recognition (Google) sometimes mishears times; say "from 6:10 to 6:40 PM" in one go.
- The CALL button is still a placeholder.

## Development notes

Check `git status` before every commit: `.env`, `logs/`, `memory_data/`, `Schedule_data/` and `models/` must not appear.

```bash
git add .
git commit -m "V0.6: wake word, schedule, reminders"
git push
git tag -a v0.6 -m "Jarvis V0.6 - wake word, schedule, reminders"
git push origin v0.6
```

**Current version:** V0.6, wake word, schedule and reminders