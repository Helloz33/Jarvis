"""Run every test:  python tests/run_all.py   (needs: pip install -r requirements-dev.txt)
Tests use a temporary data folder, so your real schedule and memories are never touched."""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
failed = []
for test in sorted(HERE.glob("test_*.py")):
    result = subprocess.run([sys.executable, str(test)], capture_output=True, text=True, timeout=600)
    last = (result.stdout.strip().splitlines() or ["(no output)"])[-1]
    print(f"{'ok  ' if result.returncode == 0 else 'FAIL'} {test.name}: {last if result.returncode == 0 else ''}")
    if result.returncode:
        failed.append(test.name)
        print(result.stderr[-1500:])
print("ALL PASSED" if not failed else f"FAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
