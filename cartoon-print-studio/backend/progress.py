"""Per-session progress logger.

Writes JSONL events to data/{sid}/_progress.log so the frontend can poll
for real-time progress updates during long-running tasks.

Each line: {"ts": 12345.6, "phase": "previews", "step": "minimax-2/4",
           "percent": 50, "message": "生成第 2/4 张"}
"""
import json, os, time, threading

DATA = os.path.join(os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


class Progress:
    _locks = {}
    _lock_global = threading.Lock()

    def __init__(self, sid: str, phase: str):
        self.sid = sid
        self.phase = phase
        self.path = os.path.join(DATA, sid, "_progress.log")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with Progress._lock_global:
            Progress._locks.setdefault(sid, threading.Lock())
        self._lock = Progress._locks[sid]
        self.emit("start", 0, f"开始 {phase}")

    def emit(self, step: str, percent: int, message: str):
        line = {
            "ts": round(time.time(), 3),
            "phase": self.phase,
            "step": step,
            "percent": max(0, min(100, int(percent))),
            "message": message,
        }
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                f.flush()

    def done(self, message: str = "完成"):
        self.emit("done", 100, message)

    def fail(self, message: str):
        self.emit("fail", 100, message)


def read(sid: str, since_ts: float = 0.0):
    """Return all progress events after since_ts (for polling)."""
    p = os.path.join(DATA, sid, "_progress.log")
    if not os.path.isfile(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if e.get("ts", 0) > since_ts:
                out.append(e)
    return out


def latest(sid):
    p = os.path.join(DATA, sid, "_progress.log")
    if not os.path.isfile(p):
        return None
    last = None
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            try:
                last = json.loads(line)
            except Exception:
                pass
    return last
