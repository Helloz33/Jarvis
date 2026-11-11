"""Characterization run: exercise the schedule, parsers, notes, timers and quick paths with a
frozen clock and seeded ids, and print every result as JSON.

golden_v08.json holds the output of V0.8 (before the V0.8.1 restructure). test_same_as_v08.py runs
this against the current code and checks nothing changed. Usage: python tests/characterize.py <project folder>"""
import json, random, sys, tempfile, uuid, os
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

_rng = random.Random(1234)
uuid.uuid4 = lambda: uuid.UUID(int=_rng.getrandbits(128))

from freezegun import freeze_time
fz = freeze_time("2026-11-09 12:00:00")    # a Monday
fz.start()

tmp = Path(tempfile.mkdtemp())
NEW = (ROOT / "Schedule").is_dir()
if NEW:
    import paths
    paths.use_data_root(tmp)
    import Schedule as S
    from Schedule import notes as N, timers as T, permission
    permission.ask = lambda *a, **k: True
    from Schedule import parsers as P
else:
    from Tools import schedule as S, notes as N, timers as T
    S.DATA_DIR = tmp / "Schedule_data"; S.SCHEDULE_FILE = S.DATA_DIR / "schedule.json"
    S.ask_permission = lambda *a, **k: True
    P = S
    import Memory
    Memory.store.DATA_DIR = tmp / "memory_data"
    Memory.store.PROFILE_FILE = Memory.store.DATA_DIR / "profile.md"
    Memory.store.MEMORIES_FILE = Memory.store.DATA_DIR / "memories.jsonl"

SEED = json.loads((Path(__file__).parent / "sample_schedule.json").read_text())
sched_dir = (paths.SCHEDULE_DIR if NEW else S.DATA_DIR)
sched_dir.mkdir(parents=True, exist_ok=True)
(sched_dir / "schedule.json").write_text(json.dumps(SEED))

out = []
def rec(label, value):
    try:
        json.dumps(value)
    except TypeError:
        value = repr(value)
    out.append([label, value])

def call(_lbl, fn, *a, **k):
    try:
        rec(_lbl, fn(*a, **k))
    except Exception as exc:
        rec(_lbl, f"EXC {type(exc).__name__}: {exc}")

load = (lambda: S.store._load()) if NEW else S._load

# --- parsers -------------------------------------------------------------------------------
SENTENCES = [
    "add an hour of physics at 2 pm", "add a study session from 6:10 to 6:40 pm tomorrow",
    "schedule chem review on friday at 7", "set a physics session for 3 to 4 pm",
    "what is on my schedule today", "add math practice 4 to 5", "book a 30-minute session at 9 pm called reading",
    "add 2 hours of test prep, one for math and one for chem, place it how you see fit",
    "on Friday add a 1-hour session after my club called physics prep",
    "find me some time for spanish next week", "I have 3 hours of homework on thursday",
    "set my homework to 90 minutes", "no homework friday", "mark today and tomorrow as days off from school",
    "undo the day off tomorrow", "Thursday Nov 26 is a holiday", "no school mondays",
    "remove all items on the Monday schedule", "remove the homework and physics stuff and test prep on Monday and Tuesday",
    "clear wednesday", "do it", "yes please", "go ahead", "rename the 6 to 7 session to chemistry",
    "name that session calculus", "add something at 6: 4", "school is cancelled on friday",
    "remind me to bring my charger tomorrow", "remind me at 7 pm to call dad", "don't let me forget the permission slip",
    "remind me in 30 minutes to stretch", "cross off the charger", "what do I need to remember?",
    "clear my done reminders", "remove the permission slip from my reminders", "put milk on my reminders",
    "set a 25 minute timer", "set a pasta timer for 10 minutes", "timer for an hour and a half",
    "how much time is left on my timer", "cancel all timers", "cancel the pasta timer", "set a 2 minute timer for the eggs please",
]
for s in SENTENCES:
    call(f"add:{s}", P.parse_add_request, s)
    call(f"place:{s}", P.parse_place_request, s)
    call(f"hw:{s}", P.parse_homework_request, s)
    call(f"off:{s}", P.parse_day_off_request, s)
    call(f"clear:{s}", P.parse_clear_request, s)
    call(f"confirm:{s}", P.is_confirmation, s)
    call(f"sounds:{s}", P.sounds_like_add, s)
    call(f"note:{s}", N.parse_note_request, s)
    call(f"timer:{s}", T.parse_timer_request, s)
for s in ["8 pm", "noon", "3:30 pm", "24:00", "13", "7:61"]:
    call(f"to_min:{s}", (S.timeparse._to_min if NEW else S._to_min), s)
for s in ["today", "tomorrow", "friday", "next monday", "november 24", "11/30", "2026-12-01", "jan 3", "blah"]:
    call(f"to_date:{s}", lambda x: str((S.timeparse._to_date if NEW else S._to_date)(x)), s)

# --- schedule tools ------------------------------------------------------------------------
call("list0", S.list_schedule, "today", "sunday")
call("add1", S.add_event, "Physics", "20:00", "21:00", "today")
call("add2", S.add_event, "Chem", "14:30", "", "today", duration_minutes=60)
call("add3", S.add_event, "Piano", "5 pm", "1 hour", "tuesday", repeat_days="tu,th")
call("add4", S.add_event, "Bad", "9 pm", "8 pm")
call("add5", S.add_event, "Lab", "16:00", "17:00", "wednesday", kind="fixed")
call("goal1", S.set_goal, "Physics self-study", 180, "week")
call("goal2", S.set_goal, "Spanish", 60, "week", session_minutes=30, days="mon,wed,fri")
call("plan1", S.plan_week)
call("view1", S.week_view)
call("place1", S.place_event, "Test prep", 60, 2)
call("place2", S.place_event, titles="Math prep;Chem prep", minutes=45, day="friday")
call("place3", S.place_event, "Physics prep", 60, day="monday", after="club")
call("place4", S.place_event, "Reading", 30, before="dinner", day="tuesday")
call("hw1", S.adjust_homework, 180, "thursday")
call("hw2", S.adjust_homework, 0, "friday")
call("list1", S.list_schedule, "today", "sunday")
ev = next((e for e in load()["events"] if e["title"] == "Physics"), {"id": "none"})
call("upd1", S.update_event, ev["id"], start="21:00", end="22:00")
call("upd2", S.update_event, "Physics", title="Physics HW")
call("del1", S.delete_event, "Chem")
call("del2", S.delete_event, "nonexistent")
call("off1", S.set_day_off, "wednesday", "thursday", "In-service day")
call("off2", S.set_day_off, "thursday", remove=True)
call("clear1", S.clear_day, "tuesday", what="test prep;piano")
call("clear2", S.clear_day, "friday")
call("plan2", S.plan_week, "next monday")
call("list2", S.list_schedule, "today", "next sunday")
call("view2", S.week_view, "next monday")
from datetime import datetime
for when in ["2026-11-09 15:45", "2026-11-09 16:50", "2026-11-10 17:00", "2026-11-11 18:00", "2026-11-13 19:50"]:
    call(f"due:{when}", S.due_reminders, datetime.fromisoformat(when))
call("rename1", P.find_rename_target, "rename the 7 to 8 pm session to chemistry")
call("rename2", P.find_rename_target, "name it calculus")
rec("final_data", load())

# --- notes ---------------------------------------------------------------------------------
call("n1", N.add_note, "bring charger", "tomorrow")
call("n2", N.add_note, "call dad", "", "7 pm")
call("n3", N.add_note, "permission slip")
call("n4", N.add_note, "permission slip")
call("nl1", N.list_notes)
call("nc1", N.complete_note, "charger")
call("nc2", N.complete_note, "zzz")
call("nl2", N.list_notes, True)
call("nview", N.notes_view)
call("ndue1", N.due_notes, datetime.fromisoformat("2026-11-09 19:05"))
call("ndue2", N.due_notes, datetime.fromisoformat("2026-11-10 07:45"))
call("nclear", N.clear_notes)
call("nall", N.clear_notes, False)

# --- timers --------------------------------------------------------------------------------
got = []
T.start(deliver=got.append)
call("t1", T.set_timer, 25)
call("t2", T.set_timer, 10, label="pasta")
call("t3", T.set_timer, 3, label="Pasta")
call("tl", T.list_timers)
call("tc1", T.cancel_timer, "")
call("tc2", T.cancel_timer, "pasta")
call("tc3", T.cancel_timer, all_timers=True)
call("tc4", T.cancel_timer, "")
call("t4", T.set_timer, 2000)

# --- quick paths through Agent -------------------------------------------------------------
import Agent
if NEW:
    import QuickPaths as Q
    Q.PERSONA_ON_WRITES = False
    quick_timer, quick_schedule = Q._quick_timer, Q._quick_schedule
else:
    Agent.PERSONA_ON_WRITES = False
    quick_timer, quick_schedule = Agent._quick_timer, Agent._quick_schedule
import Memory
Memory.history.messages = lambda: []
for s in ["set a 5 minute timer", "how long is left on my timers", "cancel the timer",
          "add an hour of chem review at 8 pm tomorrow", "remind me to email the teacher friday",
          "what do I need to remember", "I have 2 hours of homework on saturday",
          "add 90 minutes of reading wherever it fits", "clear saturday",
          "mark next friday as a day off", "add something at 6: 4", "rename the 8 to 9 pm session to biology"]:
    call(f"q:{s}", lambda x: quick_timer(x) or quick_schedule(x), s)

json.dump(out, sys.stdout, indent=1, default=str)
