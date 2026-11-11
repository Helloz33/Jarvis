"""The app starts, serves the page under the configured name, and the WebSocket works end to end.
Run:  python tests/test_app.py"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import paths
paths.use_data_root(tempfile.mkdtemp())
import Config
import Server as S
from fastapi.testclient import TestClient

S.session.greeted = True
with TestClient(S.app) as c:
    html = c.get("/").text
    assert "__NAME" not in html and f"<title>{Config.NAME} " in html and Config.NAME.upper() + " //" in html
    with c.websocket_connect("/ws", headers={"origin": f"http://127.0.0.1:{S.PORT}"}) as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot" and snap["name"] == Config.NAME and snap["iteration"] == S.ITERATION
        ws.send_json({"type": "list_schedule"})
        view = ws.receive_json()
        while view["type"] != "schedule":
            view = ws.receive_json()
        assert len(view["days"]) == 7 and "tasks" in view
        ws.send_json({"type": "say", "text": "set a 1 minute timer"})
        reply = None
        for _ in range(20):
            m = ws.receive_json()
            if m["type"] == "reply":
                reply = m["text"]
                break
        assert reply and reply.startswith("Timer set: 1 minute timer"), reply
    try:
        with c.websocket_connect("/ws", headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
        raise AssertionError("a foreign page could connect")
    except AssertionError:
        raise
    except Exception:
        pass
print("PASS app")
