"""The V0.8.1 restructure must not change behaviour: replay the V0.8 scenario and compare.
New fields that V0.8 did not have (an empty "tasks" list, "task": false on events) are ignored.
Run:  python tests/test_same_as_v08.py"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def norm(x):
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items() if not (k == "task" and v is False) and not (k == "tasks" and v == [])}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x


out = subprocess.run([sys.executable, str(HERE / "characterize.py"), str(HERE.parent)],
                     capture_output=True, text=True, timeout=300)
assert out.returncode == 0, out.stderr[-2000:]
new = json.loads(out.stdout)
old = json.loads((HERE / "golden_v08.json").read_text())
assert len(new) == len(old), (len(new), len(old))
bad = [(a, b) for a, b in zip(old, new) if norm(a) != norm(b)]
for a, b in bad[:5]:
    print("V0.8:", str(a)[:300]); print("now: ", str(b)[:300]); print()
assert not bad, f"{len(bad)} results changed"
print(f"PASS same as V0.8 ({len(new)} results)")
