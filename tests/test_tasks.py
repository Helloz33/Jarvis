"""Tasks with deadlines: planning, priority, warnings before losing time, progress, quick paths.
Run:  python tests/test_tasks.py"""
import json, random, sys, tempfile, uuid
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_rng = random.Random(7)
uuid.uuid4 = lambda: uuid.UUID(int=_rng.getrandbits(128))
from freezegun import freeze_time

clock = freeze_time("2026-11-09 12:00:00")       # Monday noon
clock.start()
import paths
paths.use_data_root(tempfile.mkdtemp())
import Schedule as S
from Schedule import permission, rules, tasks, timeparse as TP

asked = []
answer = {"value": True}
permission.ask = lambda action, target, detail="": asked.append((action, target, detail)) or answer["value"]
paths.SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
(paths.SCHEDULE_DIR / "schedule.json").write_text((Path(__file__).parent / "sample_schedule.json").read_text())

def data(): return S.store._load()
def sessions(title):
    return sorted((e for e in data()["events"] if e.get("task") and e["title"] == title), key=lambda e: (e["date"], e["start"]))
def minutes(evs): return sum(TP._to_min(e["end"]) - TP._to_min(e["start"]) for e in evs)
def check_no_overlap():
    d = data()
    for ev in [e for e in d["events"] if e.get("task")]:
        day = date.fromisoformat(ev["date"])
        for s, e, t in rules._busy(d, day, ignore=ev["id"]):
            assert not (TP._to_min(ev["start"]) < e and s < TP._to_min(ev["end"])), (ev, t)
def ok(cond, msg=""):
    assert cond, msg

# 1. add and plan: 4 hours before Friday, finished by Wednesday (1-day buffer), never on top of anything
r = S.add_task("History essay", "friday", hours=4)
print(r)
ok(r.startswith("Added task: History essay, due Fri Nov 13, about 4 hours, normal priority"), r)
ess = sessions("History essay")
ok(minutes(ess) == 240, ess)
ok(all(e["date"] <= "2026-11-11" for e in ess), ess)
check_no_overlap()
cap = {}
for e in data()["events"]:
    if e.get("task"):
        cap[e["date"]] = cap.get(e["date"], 0) + TP._to_min(e["end"]) - TP._to_min(e["start"])
ok(max(cap.values()) <= 180, cap)
ok(r.count("Mon Nov 9") >= 1 and "Tue Nov 10" in r, r)

# 2. a second task competes; planning is incremental (the essay's sessions do not move)
before = [(e["date"], e["start"]) for e in sessions("History essay")]
r2 = S.add_task("Chem lab report", "next monday", minutes=180, importance="low")
print(r2)
ok([(e["date"], e["start"]) for e in sessions("History essay")] == before)
ok(minutes(sessions("Chem lab report")) == 180)
check_no_overlap()

# 3. progress trims the surplus; done removes the rest
r = S.log_task_progress("essay", minutes=60)
ok(r == "Logged 1 hour on History essay; 3 hours left.", r)
ok(minutes(sessions("History essay")) == 180, sessions("History essay"))

# 4. deleting a session of a normal task that still fits: no question, re-planned elsewhere (not the same slot)
first = sessions("History essay")[0]
asked.clear()
r = S.delete_event(first["id"])
print(r)
ok(not asked, asked)
ok(r.startswith("Deleted event: History essay") and "History essay moved to" in r, r)
ok(minutes(sessions("History essay")) == 180)
ok(all((e["date"], e["start"]) != (first["date"], first["start"]) for e in sessions("History essay")))
check_no_overlap()

# 5. high priority always asks before losing time; saying no changes nothing
S.update_task("essay", importance="high")
ok(tasks.effective_priority(data(), data()["tasks"][0]) == "high")
victim = sessions("History essay")[0]
asked.clear(); answer["value"] = False
r = S.delete_event(victim["id"])
ok("declined" in r and len(asked) == 1 and "History essay" in asked[0][2], (r, asked))
ok(any(e["id"] == victim["id"] for e in data()["events"]))
answer["value"] = True

# 6. an event on top of a planned session: checked, then the session moves
target = sessions("Chem lab report")[0]
asked.clear()
r = S.add_event("Dentist", TP._fmt(TP._to_min(target["start"])), TP._fmt(TP._to_min(target["end"])), target["date"])
print(r)
ok(r.startswith("Added flexible event: Dentist"), r)
ok(minutes(sessions("Chem lab report")) == 180)
check_no_overlap()

# 7. clear a day that holds task work: impact is checked; time goes to other days
day = sessions("Chem lab report")[0]["date"]
r = S.clear_day(day, what="chem lab report")
print(r)
ok(r.startswith("Cleared") and minutes(sessions("Chem lab report")) == 180, r)
ok(all(e["date"] != day for e in sessions("Chem lab report") if e["date"] >= "2026-11-09"))

# 8. impossible: a huge estimate does not fit and says so
r = S.add_task("Physics project", "wednesday", hours=30)
print(r)
ok("does not fit" in r, r)
ok("treating it as high priority" in r, r)          # urgency raised it: due in 2 days
S.delete_task("physics project")

# 9. urgency rises as the due date comes closer (announced once)
clock.stop(); clock = freeze_time("2026-11-15 12:00:00"); clock.start()     # Sunday; chem due Monday
d = data(); chem = next(t for t in d["tasks"] if t["title"] == "Chem lab report")
ok(tasks.effective_priority(d, chem) == "high")
msg = S.plan_tasks()
ok("Chem lab report is due tomorrow, so I'm treating it as high priority now." in msg, msg)
ok("treating" not in S.plan_tasks())

# 10. a missed session is planned again (no progress was reported)
clock.stop(); clock = freeze_time("2026-11-09 12:00:00"); clock.start()
S.add_task("Spanish slides", "thursday", minutes=90)
sp = sessions("Spanish slides")
ok(minutes(sp) == 90, sp)
end = sp[0]
end_at = datetime.fromisoformat(f"{end['date']} {end['end']}")
clock.stop(); clock = freeze_time((end_at.isoformat(sep=" "))); clock.start()
S.plan_tasks()
later = [e for e in sessions("Spanish slides") if (e["date"], e["start"]) > (end["date"], end["start"])]
ok(minutes(later) == 90, sessions("Spanish slides"))

# 11. done: future sessions go away
r = S.log_task_progress("spanish slides", done=True)
ok(r == "Marked Spanish slides as done.", r)
ok(not [e for e in sessions("Spanish slides") if e["date"] > end["date"]])

# 12. homework (a priority goal) never bumps task sessions; plan_week keeps them
keep = {e["id"] for e in data()["events"] if e.get("task")}
S.plan_week()
ok(keep <= {e["id"] for e in data()["events"]})
check_no_overlap()

# 13. reminders and the SCHEDULE tab
s0 = sessions("History essay")[0]
due = S.due_reminders(datetime.fromisoformat(f"{s0['date']} {s0['start']}"))
line = next(x["text"] for x in due if x["title"] == "History essay")
ok(line.startswith("Sir, time to work on History essay,"), line)
v = S.week_view()
ok(any(t["title"] == "History essay" and t["priority"] == "high" for t in v["tasks"]), v["tasks"])
ok(any(e["task"] for d in v["days"] for e in d["events"]))

# 14. the direct path, by voice
import Memory, QuickPaths as Q
Q.PERSONA_ON_WRITES = False
said = []
Memory.history.messages = lambda: [{"role": "user", "content": said[-1]}] if said else []
def say(text):
    reply = Q.quick_reply(text); said.append(text); print(f"> {text}\n  {reply}"); return reply
ok(say("I have an english essay due friday") == "How long do you think the english essay will take?")
r = say("about 2 hours")
ok(r.startswith("Added English essay, due Fri Nov 13, about 2 hours, normal priority.") and "I planned" in r, r)
ok(say("I have a big chem test on friday").startswith("How many hours of studying do you want for the chem test?"))
r = say("three hours")
ok("high priority" in r, r)
r = say("what's due this week?")
ok("English essay: due Fri Nov 13" in r and "[" not in r, r)
ok(say("I did 30 minutes of the english essay") == "Logged 30 minutes on English essay; 1.5 hours left.")
ok(say("how much is left on the english essay?").startswith("English essay: due Fri Nov 13, 1.5 hours left"))
ok(say("make the english essay low priority").startswith("Updated English essay: low priority."))
ok(say("the english essay is done") == "Marked English essay as done.")
ok(say("remove the chem test task") == "Removed the task Chem test and its planned sessions.")
ok(Q.quick_reply("remind me to bring my charger tomorrow").startswith("Noted"))     # notes still work
print("PASS tasks")

# 15. titles are cleaned however the request was worded (speech often drops the "I")
from Schedule.tasks import clean_title
for said, want in [("have a chem lab report", "Chem lab report"), ("I have to finish my history essay", "History essay"),
                   ("I've got a physics worksheet", "Physics worksheet"), ("so I have to study for the chem test", "Chem test"),
                   ("I gotta write an english essay", "English essay"), ("Chem lab report", "Chem lab report")]:
    ok(clean_title(said) == want, (said, clean_title(said)))
ok(S.parsers.parse_task_request("have a bio report due friday, 2 hours")["title"] == "Bio report")
d = data(); d["tasks"].append({"id": "zz99", "title": "Have a geo poster", "due": "2026-11-20", "due_time": "", "estimate": 60,
                               "done": 0, "importance": "normal", "status": "open"}); S.store._save(d)
S.plan_tasks()
ok(next(t for t in data()["tasks"] if t["id"] == "zz99")["title"] == "Geo poster")
print("PASS titles")

# 16. finding a task however it is named ("I have a chem lab report", "the assignment called ...")
S.add_task("Bio report", "next friday", minutes=60)
ok(tasks._find(data(), "I have a bio report")[0]["title"] == "Bio report")
r = Q.quick_reply("I have an assignment called I have a bio report could you remove it")
ok(r == "Removed the task Bio report and its planned sessions.", r)
print("PASS find")

# 17. "remove chem lab report tasks from my schedule" is understood directly
S.add_task("Chem lab report", "next friday", minutes=60)
for said in ["remove chem lab report tasks from my schedule", "remove the chem lab report from my schedule"]:
    p = S.parsers.parse_task_request(said)
    ok(p and p["action"] == "delete", (said, p))
ok(Q.quick_reply("remove chem lab report tasks from my schedule") == "Removed the task Chem lab report and its planned sessions.")
ok(S.parsers.parse_task_request("remove the homework on monday") is None)        # clearing a day still works
import Agent
ok(Agent._claims_schedule_change("Done.", "remove chem lab report from my schedule"))
ok(Agent._claims_schedule_change("Done, sir.", "delete the essay"))
ok(not Agent._claims_schedule_change("Done.", "what's the weather"))
print("PASS remove")