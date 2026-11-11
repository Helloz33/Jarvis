"""Memory is saved however a session ends (V0.8), now stored through the paths module.
Run:  python tests/test_memory.py"""
import json, sys, tempfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths
paths.use_data_root(tempfile.mkdtemp())
import Memory
from Memory import store
Memory.embeddings.embed = lambda text: None
calls = []
Memory.summarize = lambda turns, model: calls.append(len(turns)) or f"User talked about {turns[0][0]}."
cur = paths.MEMORY_DIR / "session_current.json"

Memory.history.add_turn("plan my week", "Done.")
assert json.loads(cur.read_text())["turns"] == [["plan my week", "Done."]]
for i in range(14):
    Memory.history.add_turn(f"q{i}", f"a{i}")
assert len(Memory.history.messages()) == 20 and len(Memory.history.snapshot()) == 15
assert Memory.end_session("m", wait=True) is True and calls == [15] and not cur.exists()
assert len(store.load_memories()) == 1
Memory.history.add_turn("what's on friday", "Gym at 3."); Memory.history.add_turn("thanks", "Anytime.")
Memory.history = type(Memory.history)()                      # the app died: RAM is gone, the file is not
Memory.history.on_change = Memory._persist
assert cur.exists() and Memory.recover_session("m") is True
for _ in range(50):
    if len(store.load_memories()) == 2:
        break
    time.sleep(0.05)
assert len(store.load_memories()) == 2 and not cur.exists()
store.append_profile("Likes physics")
assert "Likes physics" in store.read_profile() and (paths.MEMORY_DIR / "profile.md").exists()
print("PASS memory")
