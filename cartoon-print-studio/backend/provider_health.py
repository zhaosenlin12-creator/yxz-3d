"""One shared circuit breaker for every external service.

The workstation talks to a handful of providers that live outside this
machine: Tripo3D, Tencent Hunyuan3D Cloud, AIXJ, MiniMax, jojo, Edge
TTS, the local voice box and the LLM gateways.  Each of them fails in its
own way and on its own schedule, and before this module every caller kept
its own private cooldown list.  That produced three recurring problems:

* **Whack-a-mole.**  A failure in one provider was only remembered by the
  code that happened to call it, so the next request walked into the same
  dead end again -- and the visitor waited for it.
* **Restart amnesia.**  The cooldowns lived in memory, so a backend
  restart made the app try the provider that had just failed, exactly
  when it was most likely to fail again.
* **Silent quality loss.**  When every cloud engine was down, the chain
  fell through to the local relief model and produced a hundred broken
  fragments.  That looked like "the model quality dropped" instead of
  "the network was down", which is why every outage turned into a
  round of guessing.

This module is the single place that remembers which providers are
currently unusable, how long they stay unusable and when they may be
retried.  Callers ask before they dial out and report what happened
afterwards.

States
------
``healthy``
    The last call succeeded.  The provider may be used.
``degraded``
    A few calls failed in a row.  The provider still works, but a chain
    that has an alternative should prefer it.
``open``
    The provider is unusable for a while.  Callers skip it entirely
    instead of waiting for a timeout.

After the cooldown expires the provider is *half open*: the next caller
is allowed to try it.  Success closes it, another failure opens it for
longer.
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict


def _data_dir() -> str:
    """Where the state file lives (the same place the rest of the data is)."""
    return os.environ.get("CARTOON_DATA_DIR") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
    )


def _state_file() -> str:
    """Where the state is kept.

    Resolved on every use so a change of CARTOON_DATA_DIR (the test suite
    does that) cannot leave the breaker writing into another directory.
    """
    return os.path.join(_data_dir(), "provider_health.json")


STATE_FILE = _state_file()

# How long a provider stays unusable after a failure of each kind.
# "network" is a DNS answer that did not come back or a TLS handshake that
# timed out -- these usually clear within a minute.  "quota" means the
# account is spent, which does not clear by itself.
COOLDOWNS: Dict[str, float] = {
    "network": 45.0,
    "server": 30.0,
    "unknown": 60.0,
    "auth": 900.0,
    "quota": 3600.0,
}

# A provider that keeps failing gets a longer cooldown, but never more
# than this multiple of its base value.
BACKOFF_MULTIPLIER = 1.5
MAX_BACKOFF_FACTOR = 5.0

# How many failures in a row turn a provider "degraded" (usable, but the
# chain should look for another one first).
DEGRADE_AFTER = 2

_LOCK = threading.RLock()
_STATE: Dict[str, Dict[str, Any]] = {}


def _default_record() -> Dict[str, Any]:
    return {
        "state": "healthy",
        "failures": 0,
        "open_until": 0.0,
        "last_error": "",
        "last_failure_kind": "",
        "last_success": 0.0,
        "last_failure": 0.0,
    }


def _load_locked() -> None:
    """Read the state file once; a corrupt file must not stop the app."""
    if _STATE:
        return
    try:
        with open(_state_file(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        for name, value in raw.items():
            if not isinstance(value, dict):
                continue
            record = _default_record()
            record.update({k: v for k, v in value.items() if k in record})
            _STATE[str(name)] = record


def _save_locked() -> None:
    """Persist the state so a restart does not forget a dead provider."""
    try:
        target = _state_file()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(_STATE, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, target)
    except Exception:
        # Persistence is a nice-to-have; losing it must never break a call.
        pass


def _cooldown_for(kind: str, failures: int) -> float:
    base = COOLDOWNS.get(kind, COOLDOWNS["unknown"])
    factor = min(MAX_BACKOFF_FACTOR, BACKOFF_MULTIPLIER ** max(0, failures - 1))
    return base * factor


def report_success(provider: str) -> None:
    """Record that the provider answered.  Closes an open circuit."""
    name = (provider or "").strip()
    if not name:
        return
    with _LOCK:
        _load_locked()
        record = _STATE.setdefault(name, _default_record())
        record["state"] = "healthy"
        record["failures"] = 0
        record["open_until"] = 0.0
        record["last_success"] = time.time()
        _save_locked()


def report_failure(provider: str, kind: str = "unknown", detail: str = "") -> float:
    """Record a failure and return the cooldown that was applied.

    ``kind`` decides how long the provider stays unusable: ``network``,
    ``server``, ``auth``, ``quota`` or ``unknown``.
    """
    name = (provider or "").strip()
    if not name:
        return 0.0
    kind = (kind or "unknown").strip().lower()
    if kind not in COOLDOWNS:
        kind = "unknown"
    with _LOCK:
        _load_locked()
        record = _STATE.setdefault(name, _default_record())
        record["failures"] = int(record.get("failures", 0)) + 1
        cooldown = _cooldown_for(kind, record["failures"])
        record["state"] = "open"
        record["open_until"] = time.time() + cooldown
        record["last_error"] = (detail or "")[:400]
        record["last_failure_kind"] = kind
        record["last_failure"] = time.time()
        _save_locked()
        return cooldown


def reset(provider: str) -> None:
    """Forget everything about one provider (used by an operator)."""
    name = (provider or "").strip()
    if not name:
        return
    with _LOCK:
        _load_locked()
        _STATE.pop(name, None)
        _save_locked()


def remaining(provider: str) -> float:
    """Seconds left on the cooldown; 0 when the provider may be used."""
    name = (provider or "").strip()
    if not name:
        return 0.0
    with _LOCK:
        _load_locked()
        record = _STATE.get(name)
        if not record:
            return 0.0
        left = float(record.get("open_until", 0.0)) - time.time()
        return left if left > 0 else 0.0


def is_open(provider: str) -> bool:
    """True while the provider must be skipped."""
    return remaining(provider) > 0.0


def is_degraded(provider: str) -> bool:
    """True when the provider works but keeps failing."""
    name = (provider or "").strip()
    if not name:
        return False
    with _LOCK:
        _load_locked()
        record = _STATE.get(name)
        if not record:
            return False
        if remaining(name) > 0:
            return False
        return int(record.get("failures", 0)) >= DEGRADE_AFTER


def state(provider: str) -> Dict[str, Any]:
    """A copy of one provider's record, safe to hand to a client."""
    name = (provider or "").strip()
    with _LOCK:
        _load_locked()
        record = dict(_STATE.get(name) or _default_record())
    left = remaining(name)
    record["cooldown_remaining_s"] = round(left, 1)
    if left > 0:
        record["state"] = "open"
    return record


def snapshot() -> Dict[str, Dict[str, Any]]:
    """Every provider we know about, with its current state."""
    with _LOCK:
        _load_locked()
        names = list(_STATE.keys())
    out: Dict[str, Dict[str, Any]] = {}
    for name in names:
        out[name] = state(name)
    return out


def known_providers() -> list:
    """The providers the workstation depends on, in a stable order."""
    return [
        "tripo3d",
        "hunyuan3d",
        "aixj",
        "minimax",
        "jojo",
        "minimax-tts",
        "edge-tts",
        "voicebox",
        "llm",
    ]
