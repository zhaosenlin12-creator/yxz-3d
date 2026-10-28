"""Per-session progress logger.

Writes JSONL events to data/{sid}/_progress.log so the frontend can poll
for real-time progress updates during long-running tasks.

Each line: {"ts": 12345.6, "phase": "previews", "step": "minimax-2/4",
           "percent": 50, "message": "生成第 2/4 张"}

``stage`` is optional and carries the user-facing phase of a long running
job (queued / geometry / texturing / optimizing / done / failed).  The
frontend uses it to draw a real progress checklist instead of showing raw
engine chatter, so the wording of ``message`` may stay technical.
"""
import json, os, time, threading

DATA = os.path.join(os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Internal phase ids -> user-facing wording.  The frontend renders ``message``
# directly, so anything leaking an engine name / internal slug here would show
# up in the UI as developer chatter.
PHASE_LABELS = {
    "previews": "正在生成预览图…",
    "3d-triposr": "正在准备 3D 模型…",
    "3d-cartoon": "正在准备 3D 模型…",
    "3d-hunyuan": "正在准备 3D 模型…",
    "3d-tripo": "正在准备 3D 模型…",
    "3d-hunyuan-cloud": "正在准备 3D 模型…",
}

DEFAULT_PHASE_LABEL = "正在处理…"


class Progress:
    _locks = {}
    _lock_global = threading.Lock()

    def __init__(self, sid: str, phase: str, reset: bool = False):
        self.sid = sid
        self.phase = phase
        self.path = os.path.join(DATA, sid, "_progress.log")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with Progress._lock_global:
            Progress._locks.setdefault(sid, threading.Lock())
        self._lock = Progress._locks[sid]
        if reset:
            # A new job for the same session must not replay the previous job's
            # events, otherwise the UI briefly shows the finished state of the
            # run before the current one starts.
            with open(self.path, "w", encoding="utf-8"):
                pass
        self.emit("start", 0, PHASE_LABELS.get(phase, DEFAULT_PHASE_LABEL))

    def emit(self, step: str, percent: int, message: str, stage: str = ""):
        line = {
            "ts": round(time.time(), 3),
            "phase": self.phase,
            "step": step,
            "percent": max(0, min(100, int(percent))),
            "message": message,
        }
        if stage:
            line["stage"] = stage
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
                f.flush()

    def done(self, message: str = "完成", stage: str = "done"):
        self.emit("done", 100, message, stage)

    def fail(self, message: str, stage: str = "failed"):
        self.emit("fail", 100, message, stage)


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
