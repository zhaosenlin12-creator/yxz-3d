"""Image providers for Cartoon Print Studio.

Preferred chain: AIXJ (gpt-image-2) -> MiniMax image -> jojo-image -> local SD.

Keys are read from <install>/keys.txt (or ~/Desktop/key.txt) and classified by
label so a deepseek/aixj-llm/jojo key is never sent to the wrong provider:
  aixj-image-key             -> AIXJ image (https://aixj.vip/v1)
  minimax-image-key / sk-cp- -> MiniMax image
  jojo-image-key / jojo      -> jojo-image
"""
from __future__ import annotations
import os, time, base64, json, urllib.request, urllib.error
import re
import threading
import progress as _pg
from typing import List, Tuple, Optional

# jojo-image (legacy fallback provider)
JOJO_BASE = "https://api2.jojocode.com/v1"
JOJO_KEYS = [k for k in [os.environ.get("JOJO_IMAGE_KEY", "").strip()] if k]

# AIXJ image (primary provider, OpenAI-compatible /images/generations)
AIXJ_BASE = os.environ.get("AIXJ_IMAGE_BASE", "https://aixj.vip/v1")
AIXJ_IMAGE_KEYS = [k for k in [os.environ.get("AIXJ_IMAGE_KEY", "").strip()] if k]
AIXJ_IMAGE_MODEL = "gpt-image-2"

# MiniMax image (fallback provider)
MINIMAX_IMAGE_KEYS = [k for k in [os.environ.get("MINIMAX_IMAGE_KEY", "").strip()] if k]

# Prefer <install>/keys.txt, fall back to ~/Desktop/key.txt (Windows convenience)
_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEYFILE = (
    os.path.join(_ROOT, "keys.txt")
    if os.path.isfile(os.path.join(_ROOT, "keys.txt"))
    else os.path.expanduser(r"~\Desktop\key.txt")
)


def _classify_keys_from_file():
    """Parse keys.txt and fill AIXJ_IMAGE_KEYS / JOJO_KEYS / MINIMAX_IMAGE_KEYS.

    Label matching is case-insensitive and accepts ':' or '：'.
    sk-cp- prefixed keys without a label are treated as MiniMax as before.
    """
    if not os.path.isfile(_KEYFILE):
        return
    try:
        with open(_KEYFILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except Exception:
        return
    for line in lines:
        low = line.lower().strip()
        if not low.startswith("sk-") and not any(
                tag in low for tag in ("aixj", "jojo", "minimax", "image")):
            continue
        key = None
        label = ""
        if ":" in line or "：" in line:
            parts = re.split(r"[:：]\s*", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip().startswith("sk-"):
                key = parts[1].strip()
                label = parts[0].lower()
        elif line.strip().startswith("sk-"):
            key = line.strip()
            label = ""
        if not key:
            continue
        if "aixj" in label and "image" in label:
            if key not in AIXJ_IMAGE_KEYS:
                AIXJ_IMAGE_KEYS.append(key)
        elif "jojo" in label:
            if key not in JOJO_KEYS:
                JOJO_KEYS.append(key)
        elif "minimax" in label and "image" in label:
            if key not in MINIMAX_IMAGE_KEYS:
                MINIMAX_IMAGE_KEYS.append(key)
        elif key.startswith("sk-cp-"):
            if key not in MINIMAX_IMAGE_KEYS:
                MINIMAX_IMAGE_KEYS.append(key)


def _minimax_image_keys_from_file():
    if not os.path.isfile(_KEYFILE):
        return
    try:
        with open(_KEYFILE, "r", encoding="utf-8") as f:
            txt = f.read()
        # only sk-cp-... keys considered minimax
        for m in re.finditer(r"sk-cp-[A-Za-z0-9_\-]{30,}", txt):
            k = m.group(0)
            if k not in MINIMAX_IMAGE_KEYS:
                MINIMAX_IMAGE_KEYS.append(k)
    except Exception:
        pass


def _aixj_image_keys_from_codex_env():
    """Safety net for the aixj image key.

    The key in keys.txt can be rotated on the provider side and go stale
    (it then answers 401).  The desktop tooling keeps the live key in
    ``~/.codex/secrets/aixj.env``; picking it up here means the image chain
    keeps working without touching keys.txt by hand.
    """
    path = os.path.expanduser(r"~\.codex\secrets\aixj.env")
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except Exception:
        return
    for line in lines:
        name, _, value = line.strip().partition("=")
        key = value.strip()
        if name.strip() != "AIXJ_IMAGE_API_KEY" or not key.startswith("sk-"):
            continue
        if key not in AIXJ_IMAGE_KEYS:
            AIXJ_IMAGE_KEYS.append(key)


_classify_keys_from_file()
_minimax_image_keys_from_file()
_aixj_image_keys_from_codex_env()

# Strip empties
JOJO_KEYS = [k for k in JOJO_KEYS if k]
AIXJ_IMAGE_KEYS = [k for k in AIXJ_IMAGE_KEYS if k]
MINIMAX_IMAGE_KEYS = [k for k in MINIMAX_IMAGE_KEYS if k]

JOJO_KEY = JOJO_KEYS[0] if JOJO_KEYS else ""
AIXJ_IMAGE_KEY = AIXJ_IMAGE_KEYS[0] if AIXJ_IMAGE_KEYS else ""


def has_cloud_image_keys() -> bool:
    """True when at least one cloud image provider has a key loaded."""
    return bool(AIXJ_IMAGE_KEYS or MINIMAX_IMAGE_KEYS or JOJO_KEYS)

# Per-key circuit breaker. When a key returns 401/402/403 or quota /
# balance text, we blacklist it for the rest of this process so we
# don't waste 60s * N retrying a known-dead provider. Reset on restart.
_JOJO_DEAD_KEYS: set = set()
_JOJO_DEAD_UNTIL: dict = {}
_AIXJ_DEAD_KEYS: set = set()

# MiniMax answers HTTP 200 with a business error when the account runs out
# of credits ("status_code": 2056, "已达到 Token Plan 上限").  Without a
# breaker every single picture first burns a doomed call on that key before
# the second key picks the work up, so the batch pays for the outage twice.
_MINIMAX_DEAD_KEYS: set = set()
_MINIMAX_DEAD_UNTIL: dict = {}

#: Business codes that mean "this key is out of credit" rather than
#: "this request was bad".  Everything else stays retryable.  2013 is a
#: bad-request code ("unsupported model"), so it must never retire a key.
_MINIMAX_QUOTA_CODES = (2056, 1004, 1008, 1027)


def _minimax_quota_error(base: dict) -> bool:
    """True when a MiniMax business error means the key is spent."""
    code = base.get("status_code")
    if code in _MINIMAX_QUOTA_CODES:
        return True
    msg = str(base.get("status_msg") or "").lower()
    return any(x in msg for x in
               ("token plan", "quota", "insufficient", "余额", "额度", "欠费", "已达上限"))

# Every visitor on the network can ask for preview images at the same time.
# Firing N users x N prompts straight at the provider makes it rate-limit
# us, and every call then burns its full timeout before failing -- that is
# what made the guided flow die on a busy machine.  A single global gate
# keeps the outbound pressure constant: extra requests wait their turn
# instead of piling onto the provider and timing out.
#
# 12 slots = three full 4-image requests in flight at once, which is what
# the image keys are provisioned for.  Raise it with YXZ_IMAGE_CONCURRENCY
# when the provider has more headroom.
OUTBOUND_LIMIT = max(1, int(os.environ.get("YXZ_IMAGE_CONCURRENCY", "12") or 12))
OUTBOUND_QUEUE_TIMEOUT = max(30.0, float(os.environ.get("YXZ_IMAGE_QUEUE_TIMEOUT", "240") or 240))

# Per-provider gates.  The AIXJ gateway only has one key and it starts
# dropping TLS handshakes ("handshake operation timed out", ECONNRESET)
# once too many requests land on it at once.  Six parallel calls against
# it means four of them burn a full 90s timeout and then a 90s retry --
# that is what turned one slow preview into a four-minute wait.  Keeping
# each provider inside its own lane fixes that without capping the whole
# machine at one request at a time.
AIXJ_CONCURRENCY = max(1, int(os.environ.get("YXZ_AIXJ_CONCURRENCY", "3") or 3))
MINIMAX_CONCURRENCY = max(1, int(os.environ.get("YXZ_MINIMAX_CONCURRENCY", "6") or 6))
JOJO_CONCURRENCY = max(1, int(os.environ.get("YXZ_JOJO_CONCURRENCY", "3") or 3))
DOWNLOAD_CONCURRENCY = max(1, int(os.environ.get("YXZ_DOWNLOAD_CONCURRENCY", "6") or 6))

_OUTBOUND_SEMAPHORE = threading.BoundedSemaphore(OUTBOUND_LIMIT)
_AIXJ_SEMAPHORE = threading.BoundedSemaphore(AIXJ_CONCURRENCY)
_MINIMAX_SEMAPHORE = threading.BoundedSemaphore(MINIMAX_CONCURRENCY)
_JOJO_SEMAPHORE = threading.BoundedSemaphore(JOJO_CONCURRENCY)
_DOWNLOAD_SEMAPHORE = threading.BoundedSemaphore(DOWNLOAD_CONCURRENCY)


class _OutboundSlot:
    """Context manager that holds one of the global outbound slots."""

    def __init__(self, semaphore=None, timeout: Optional[float] = None):
        self.semaphore = semaphore if semaphore is not None else _OUTBOUND_SEMAPHORE
        self.timeout = timeout
        self._held = False

    def __enter__(self):
        if self.timeout is None:
            self._held = self.semaphore.acquire(timeout=OUTBOUND_QUEUE_TIMEOUT)
        else:
            self._held = self.semaphore.acquire(timeout=self.timeout)
        if not self._held:
            raise TimeoutError("image provider queue is full")
        return self

    def __exit__(self, *exc):
        if self._held:
            self._held = False
            self.semaphore.release()
        return False
_AIXJ_DEAD_UNTIL: dict = {}


def _prepare_reference(image_bytes: bytes, max_side: int = 1024) -> Optional[bytes]:
    """Shrink a reference picture into a small JPEG.

    The image providers choke on multi-megabyte uploads, so the reference is
    scaled down and re-encoded before it is sent.  Returns None when the
    bytes cannot be decoded as an image.
    """
    if not image_bytes:
        return None
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(image_bytes)) as decoded:
            decoded = decoded.convert("RGB")
            width, height = decoded.size
            scale = min(1.0, max_side / float(max(width, height) or 1))
            if scale < 1.0:
                decoded = decoded.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.LANCZOS,
                )
            buffer = io.BytesIO()
            decoded.save(buffer, format="JPEG", quality=85)
            return buffer.getvalue()
    except Exception:
        return None


def _download_with_retry(url: str, ua: str = "", attempts: int = 3,
                         timeout: float = 30.0) -> Optional[bytes]:
    """Fetch a generated image, retrying a couple of times.

    The image host sits behind a CDN that regularly drops the TLS
    handshake when several downloads land at once.  The generation call
    has already been paid for at that point, so throwing the picture away
    and regenerating it costs another minute -- retrying the download is
    far cheaper.
    """
    headers = {"User-Agent": ua} if ua else {}
    last_error = ""
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with _OutboundSlot(_DOWNLOAD_SEMAPHORE):
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    data = r.read()
            if data:
                return data
            last_error = "empty body"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if attempt < attempts - 1:
            time.sleep(1.5 * (attempt + 1))
    print(f"[download] give up after {attempts} tries: {last_error[:160]}")
    return None


def _report_provider(name: str, kind: str, detail: str = "") -> None:
    """Tell the shared circuit breaker how the provider is doing.

    "ok" closes the circuit; every other kind opens it for a while, so the
    next request skips a provider that is known to be down instead of
    waiting for the same timeout again.
    """
    try:
        import provider_health
        if kind == "ok":
            provider_health.report_success(name)
        else:
            provider_health.report_failure(name, kind, detail)
    except Exception:
        pass


def _report_key_failure(name: str, kind: str, detail: str = "") -> None:
    """Report a failure that only took out one key of a multi-key service.

    The image services are used with more than one key, so a single key
    running out of credit says nothing about the others.  Reporting it as
    a full provider failure opened the shared circuit and made the chain
    skip a service that still had a working key.
    """
    try:
        import provider_health
        provider_health.report_partial_failure(name, kind, detail)
    except Exception:
        pass


def _provider_has_live_key(name: str) -> bool:
    """True when at least one key of this provider is still usable."""
    if name == "aixj":
        return any(key not in _AIXJ_DEAD_KEYS for key in AIXJ_IMAGE_KEYS)
    if name == "minimax":
        return any(key not in _MINIMAX_DEAD_KEYS for key in MINIMAX_IMAGE_KEYS)
    if name == "jojo":
        return any(key not in _JOJO_DEAD_KEYS for key in JOJO_KEYS)
    return True


def _report_key_dead(name: str, kind: str, detail: str = "") -> None:
    """Report that one key of a provider is gone.

    The shared circuit is only opened when the last usable key is gone:
    until then the provider still works and must stay in the chain.
    """
    if _provider_has_live_key(name):
        _report_key_failure(name, kind, detail)
    else:
        _report_provider(name, kind, detail)


def _provider_is_open(name: str) -> bool:
    """True when the shared breaker says this provider must be skipped.

    The breaker is the one place that remembers "this service died ten
    minutes ago".  The chain has to ask it before dialling out: a key
    whose balance is gone answers with an error after a dozen seconds,
    and four of those in a row is more than a minute of the visitor
    watching a frozen bubble.
    """
    try:
        import provider_health
        return bool(provider_health.is_open(name))
    except Exception:
        return False


def _aixj_image_call(prompt, *, n=1, size="1024x1024", model=AIXJ_IMAGE_MODEL,
                     timeout=150, sid=None) -> Optional[List[bytes]]:
    """Call AIXJ images/generations (OpenAI-compatible) with per-key retry.

    Endpoint shape: POST {base}/images/generations
    Request body: {"model": "gpt-image-2", "prompt": "...", "n": 1, "size": "1024x1024"}
    Response: {"data": [{"url": "https://..."}], ...}

    Per-key circuit breaker; returns the first successful batch of PNG bytes
    or None. gpt-image-1 is flaky (502) on this gateway, so the default model
    is gpt-image-2.
    """
    if not AIXJ_IMAGE_KEYS:
        return None
    body = {"model": model, "prompt": prompt, "n": n, "size": size}
    data = json.dumps(body).encode("utf-8")
    n_keys = len(AIXJ_IMAGE_KEYS)
    for ki, key in enumerate(AIXJ_IMAGE_KEYS):
        if sid:
            _pg.Progress(sid, "previews").emit(
                "aixj-trying", 5, f"正在准备预览图（{ki+1}/{n_keys}）…")
        if key in _AIXJ_DEAD_KEYS:
            print(f"[aixj] skip dead key {ki+1}/{n_keys}", flush=True)
            continue
        payload = None
        # The relay's upstream is flaky: a 502 means "try again in a
        # moment", not "this key is broken".  AIXJ carries the best picture
        # quality of the whole chain, so a couple of retries with a short
        # back-up beat dropping to a worse provider straight away.
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    AIXJ_BASE + "/images/generations",
                    data=data, method="POST",
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                )
                with _OutboundSlot(_AIXJ_SEMAPHORE):
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        payload = json.loads(r.read().decode("utf-8", "ignore"))
                break
            except urllib.error.HTTPError as e:
                try:
                    err = e.read().decode("utf-8", "ignore")
                except Exception:
                    err = str(e.reason)
                low = err.lower()
                dead = e.code in (401, 402, 403) or any(
                    x in low for x in ("quota", "balance", "insufficient")
                ) or ("invalid" in low and "key" in low)
                if dead:
                    _AIXJ_DEAD_KEYS.add(key)
                    _report_key_dead("aixj", "quota", f"HTTP {e.code}")
                    print(f"[aixj] key {ki+1}/{n_keys} DEAD (HTTP {e.code}): {err[:120]}", flush=True)
                    payload = None
                    break
                _report_provider("aixj", "server", f"HTTP {e.code}")
                print(f"[aixj] key {ki+1}/{n_keys} HTTP {e.code} "
                      f"(try {attempt+1}/3): {err[:160]}", flush=True)
                if e.code in (502, 503, 504) and attempt < 2:
                    time.sleep(3.0 * (attempt + 1))
                    continue
                payload = None
                break
            except Exception as e:
                _report_provider("aixj", "network", f"{type(e).__name__}: {str(e)[:120]}")
                print(f"[aixj] key {ki+1}/{n_keys} {type(e).__name__} "
                      f"(try {attempt+1}/3): {str(e)[:160]}", flush=True)
                if attempt < 2:
                    time.sleep(3.0 * (attempt + 1))
                    continue
                payload = None
                break
        if payload is None:
            continue
        out = []
        # The image host (Cloudflare R2 gateway) blocks non-browser requests
        # (403 / error 1010) unless a real User-Agent is sent.
        _DL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        for item in payload.get("data") or []:
            url = item.get("url")
            b64 = item.get("b64_json")
            if b64:
                try:
                    out.append(base64.b64decode(b64))
                except Exception:
                    pass
                continue
            if url:
                blob = _download_with_retry(url, ua=_DL_UA)
                if blob is not None:
                    out.append(blob)
        if out:
            _report_provider("aixj", "ok")
            return out
        print(f"[aixj] key {ki+1}/{n_keys} returned no images")
    return None


def _jojo_call(prompt: str, *, n: int = 1, size: str = "1024x1024",
               model: str = "gpt-image-2", timeout: float = 45.0,
               sid: Optional[str] = None, tag: str = "") -> Optional[List[bytes]]:
    """Call jojo-image API with per-key retry + timeout + progress events.

    Iterates over every key in JOJO_KEYS. For each key: one HTTP attempt
    with `timeout`. On any failure (network, HTTP 4xx/5xx, parse error)
    the next key is tried. Returns the first successful batch of PNG bytes,
    or None if all keys fail. Emits a progress event per attempt so the
    frontend sees what is happening.
    """
    if not JOJO_KEYS:
        return None
    body = {"model": model, "prompt": prompt, "n": n, "size": size}
    data = json.dumps(body).encode("utf-8")
    n_keys = len(JOJO_KEYS)
    for ki, key in enumerate(JOJO_KEYS):
        if sid:
            _pg.Progress(sid, "previews").emit(
                "jojo-trying", 5, f"正在准备预览图（{ki+1}/{n_keys}）…")
        # Skip keys we already know are dead this session.
        import time as _t
        if key in _JOJO_DEAD_KEYS and _JOJO_DEAD_UNTIL.get(key, 0) < _t.time():
            _JOJO_DEAD_KEYS.discard(key)
        if key in _JOJO_DEAD_KEYS:
            print(f"[jojo] skip dead key {ki+1}/{n_keys}", flush=True)
            continue
        try:
            req = urllib.request.Request(
                JOJO_BASE + "/images/generations",
                data=data, method="POST",
                headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            )
            with _OutboundSlot(_JOJO_SEMAPHORE):
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    payload = json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            try: err = e.read().decode("utf-8", "ignore")
            except Exception: err = str(e.reason)
            low = err.lower()
            # Quota / balance / auth errors -> blacklist this key for the rest of the run.
            if e.code in (401, 402, 403) or any(
                x in low for x in ("quota", "balance", "insufficient")
            ) or any(x in err for x in ("\u4f59\u989d", "\u4f59\u989d\u4e0d\u8db3")):
                _JOJO_DEAD_KEYS.add(key)
                _JOJO_DEAD_UNTIL[key] = _t.time() + 3600
                _report_key_dead("jojo", "quota", f"HTTP {e.code}")
                print(f"[jojo] key {ki+1}/{n_keys} DEAD (HTTP {e.code}): {err[:120]} - skipping rest of run", flush=True)
                if sid:
                    _pg.Progress(sid, "previews").emit("jojo-key-dead", 5, "某个出图服务暂时不可用，正在跳过…")
                continue
            _report_provider("jojo", "server", f"HTTP {e.code}")
            print(f"[jojo] key {ki+1}/{n_keys} HTTP {e.code}: {err[:160]}")
            continue
        except Exception as e:
            _report_provider("jojo", "network", f"{type(e).__name__}: {str(e)[:120]}")
            print(f"[jojo] key {ki+1}/{n_keys} {type(e).__name__}: {str(e)[:160]}")
            continue
        out = []
        for item in payload.get("data") or []:
            b64 = item.get("b64_json") or item.get("b64")
            if not b64: continue
            try: out.append(base64.b64decode(b64))
            except Exception: pass
        if out:
            _report_provider("jojo", "ok")
            return out
        print(f"[jojo] key {ki+1}/{n_keys} returned no images")
    return None


# ---------------------------------------------------------------------------
# MiniMax (Hailuo) image API - fallback provider
#
# Two model lines answer behind the same key:
#   * MiniMax-H3-Image -- the current line.  It lives on the OpenAI
#     compatible endpoints POST /v1/images/generations (text to picture)
#     and POST /v1/images/edits (picture to picture), and answers with
#     {"data": [{"revised_prompt": ..., "size": ..., "url": "..."}]}.
#   * image-01 -- the older line on /v1/image_generation, answering with
#     {"data": {"image_urls": [...]}}.
# H3 is tried first because it is the sharper model; image-01 stays behind
# it as the safety net so a H3 outage never means "no preview picture".
# ---------------------------------------------------------------------------
MINIMAX_IMAGE_BASE = (
    os.environ.get("MINIMAX_IMAGE_BASE", "https://api.minimaxi.com")
    or "https://api.minimaxi.com"
).rstrip("/")
MINIMAX_IMAGE_ENDPOINTS = [
    MINIMAX_IMAGE_BASE + "/v1/image_generation",
]
MINIMAX_H3_MODEL = os.environ.get("MINIMAX_IMAGE_MODEL", "MiniMax-H3-Image")
MINIMAX_H3_FAST_MODEL = "MiniMax-H3-Image-Highspeed"
MINIMAX_H3_GENERATIONS = MINIMAX_IMAGE_BASE + "/v1/images/generations"
MINIMAX_H3_EDITS = MINIMAX_IMAGE_BASE + "/v1/images/edits"


def _aspect_for(size: str) -> str:
    """Map a pixel size onto the aspect ratio the legacy line expects."""
    text = (size or "").lower().replace("*", "x").replace("×", "x")
    if text in ("1536x1024",):
        return "16:9"
    if text in ("1024x1536",):
        return "9:16"
    return "1:1"


def _h3_size(size: str) -> str:
    """Normalise a size into the "WxH" form H3 accepts.

    H3 refuses anything outside 655,360 - 20,000,000 pixels and outside a
    1:3 .. 3:1 aspect ratio, so a strange size is nudged back to the safe
    square instead of burning the request on a 400.
    """
    text = (size or "").lower().replace("*", "x").replace("×", "x")
    match = re.match(r"^\s*(\d{2,5})\s*x\s*(\d{2,5})\s*$", text)
    if not match:
        return "1024x1024"
    width, height = int(match.group(1)), int(match.group(2))
    pixels = width * height
    if pixels < 655360 or pixels > 20000000:
        return "1024x1024"
    ratio = width / float(height or 1)
    if ratio < (1 / 3) or ratio > 3:
        return "1024x1024"
    return "%dx%d" % (width, height)


def _minimax_routes(has_reference: bool):
    """Ordered MiniMax fallbacks: sharpest model first, oldest line last."""
    if has_reference:
        return (
            ("h3-edit", MINIMAX_H3_EDITS, MINIMAX_H3_MODEL, "edits"),
            ("h3-edit-fast", MINIMAX_H3_EDITS, MINIMAX_H3_FAST_MODEL, "edits"),
            ("image-01-ref", MINIMAX_IMAGE_ENDPOINTS[0], "image-01", "legacy"),
        )
    return (
        ("h3", MINIMAX_H3_GENERATIONS, MINIMAX_H3_MODEL, "generations"),
        ("h3-fast", MINIMAX_H3_GENERATIONS, MINIMAX_H3_FAST_MODEL, "generations"),
        ("image-01", MINIMAX_IMAGE_ENDPOINTS[0], "image-01", "legacy"),
    )


def _minimax_body(style: str, model: str, prompt: str, n: int, size: str,
                   reference: Optional[bytes]):
    """Build the request body for one MiniMax route (None when unusable)."""
    if style == "legacy":
        body = {"model": model, "prompt": prompt,
                "aspect_ratio": _aspect_for(size), "n": n}
        # subject_reference turns the old line into an image-to-image
        # provider: the picture becomes the subject the prompt describes.
        if reference:
            small = _prepare_reference(reference)
            if small:
                body["subject_reference"] = [{
                    "type": "character",
                    "image_file": "data:image/jpeg;base64,"
                                  + base64.b64encode(small).decode(),
                }]
        return body

    body = {"model": model, "prompt": prompt, "size": _h3_size(size), "n": n}
    if style == "edits" and reference:
        small = _prepare_reference(reference)
        if not small:
            return None
        body["images"] = [{
            "image_url": "data:image/jpeg;base64," + base64.b64encode(small).decode(),
        }]
    return body


def _minimax_images_from_payload(payload: dict, n: int):
    """Pull the pictures out of any MiniMax response shape.

    H3 answers {"data": [{"url": ...}]}; the old line answers
    {"data": {"image_urls": [...]}}; some gateways send b64_json instead.
    """
    blobs, urls = [], []
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            b64 = item.get("b64_json") or item.get("b64")
            if b64:
                blobs.append(b64)
                continue
            url = item.get("url") or item.get("image_url")
            if url:
                urls.append(url)
    elif isinstance(data, dict):
        for url in (data.get("image_urls") or []):
            if isinstance(url, str):
                urls.append(url)
        for item in (data.get("images") or []):
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict):
                b64 = item.get("b64_json") or item.get("b64")
                if b64:
                    blobs.append(b64)
                else:
                    url = item.get("url") or item.get("image_url")
                    if url:
                        urls.append(url)
    for url in (payload.get("image_urls") or []):
        if isinstance(url, str):
            urls.append(url)

    out = []
    for b64 in blobs:
        try:
            out.append(base64.b64decode(b64))
        except Exception:
            pass
    for url in urls[:max(0, n - len(out))]:
        blob = _download_with_retry(url, ua=_DL_UA, timeout=30.0)
        if blob is not None:
            out.append(blob)
    return out


def _minimax_image_call(prompt, *, n=1, size="1024x1024", model=None,
    timeout=120, sid=None, reference=None):
    """Call the MiniMax image API with per-key retry + per-attempt timeout.

    Routes, in order:
      1. MiniMax-H3-Image on POST /v1/images/generations
      2. MiniMax-H3-Image-Highspeed on the same endpoint
      3. the older image-01 line on POST /v1/image_generation
    With a reference picture the first two routes move to
    POST /v1/images/edits and carry the picture as ``images``.

    Every route walks every key, so a single spent key never costs the whole
    batch: the second key picks the work up.  Key rejection (HTTP 401/403 /
    code 2049) retires that key for the rest of the process.
    """
    if not MINIMAX_IMAGE_KEYS:
        return None
    routes = _minimax_routes(bool(reference))
    if model:
        routes = (("custom", MINIMAX_H3_GENERATIONS, model, "generations"),) + routes
    n_keys = len(MINIMAX_IMAGE_KEYS)
    for route_name, url, route_model, style in routes:
        body = _minimax_body(style, route_model, prompt, n, size, reference)
        if body is None:
            continue
        data = json.dumps(body).encode("utf-8")
        for ki, key in enumerate(MINIMAX_IMAGE_KEYS):
            if not key:
                continue
            # Skip a key that is known to be out of credit until its cooldown
            # expires -- retrying it only slows the pictures that still work.
            if key in _MINIMAX_DEAD_KEYS:
                if _MINIMAX_DEAD_UNTIL.get(key, 0) >= time.time():
                    continue
                _MINIMAX_DEAD_KEYS.discard(key)
            if sid:
                _pg.Progress(sid, "previews").emit(
                    "minimax-trying", 5, f"正在准备预览图（{ki+1}/{n_keys}）…")
            try:
                req = urllib.request.Request(
                    url, data=data, method="POST",
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                )
                with _OutboundSlot(_MINIMAX_SEMAPHORE):
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        payload = json.loads(r.read().decode("utf-8", "ignore"))
            except urllib.error.HTTPError as e:
                try:
                    err = e.read().decode("utf-8", "ignore")
                except Exception:
                    err = str(e.reason)
                # invalid api key -> abandon this key, jump to next
                if e.code in (401, 403) or "2049" in err or "invalid api key" in err.lower():
                    # Retire the key as well: leaving it out of the dead
                    # list meant every single picture tried it again and
                    # paid for the round trip.
                    _MINIMAX_DEAD_KEYS.add(key)
                    _MINIMAX_DEAD_UNTIL[key] = time.time() + 3600
                    _report_key_dead("minimax", "auth", f"HTTP {e.code}")
                    print(f"[minimax-image] key {ki+1}/{n_keys} rejected: {err[:120]}")
                    break
                if e.code == 402:
                    # No balance left on this account: retire the key so the
                    # remaining pictures go straight to a key that can pay.
                    print(f"[minimax-image] key {ki+1}/{n_keys} out of balance")
                    _MINIMAX_DEAD_KEYS.add(key)
                    _MINIMAX_DEAD_UNTIL[key] = time.time() + 3600
                    _report_key_dead("minimax", "quota", "HTTP 402")
                    break
                _report_provider("minimax", "server", f"HTTP {e.code}")
                print(f"[minimax-image] key {ki+1}/{n_keys} HTTP {e.code} {route_name}: {err[:120]}")
                continue
            except Exception as e:
                _report_provider("minimax", "network", f"{type(e).__name__}: {str(e)[:120]}")
                print(f"[minimax-image] key {ki+1}/{n_keys} {route_name} {type(e).__name__}: {str(e)[:120]}")
                continue
            base = payload.get("base_resp") or {}
            if base.get("status_code", 0) != 0 and base.get("status_msg"):
                print(f"[minimax-image] {base}")
                if _minimax_quota_error(base):
                    # The account is spent: black the key so the remaining
                    # pictures go straight to a key that can still pay.
                    _MINIMAX_DEAD_KEYS.add(key)
                    _MINIMAX_DEAD_UNTIL[key] = time.time() + 3600
                    _report_key_dead("minimax", "quota", str(base.get("status_msg"))[:120])
                    print(f"[minimax-image] key {ki+1}/{n_keys} out of credit, retiring it for an hour", flush=True)
                    if sid:
                        _pg.Progress(sid, "previews").emit(
                            "minimax-key-dead", 5, "某个出图服务额度已用完，正在换一条…")
                    break
                continue
            # The OpenAI shaped endpoints report failures as {"error": {...}}.
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error.get("message"))
                low = message.lower()
                if any(x in low for x in ("balance", "quota", "insufficient", "余额", "额度")):
                    print(f"[minimax-image] key {ki+1}/{n_keys} out of credit ({route_name})")
                    _MINIMAX_DEAD_KEYS.add(key)
                    _MINIMAX_DEAD_UNTIL[key] = time.time() + 3600
                    _report_key_dead("minimax", "quota", message[:120])
                    break
                print(f"[minimax-image] {route_name} key {ki+1}/{n_keys} error: {message[:160]}")
                continue
            out = _minimax_images_from_payload(payload, n)
            if out:
                _report_provider("minimax", "ok")
                print(f"[minimax-image] {route_name} ok with key {ki+1}/{n_keys}")
                return out
            print(f"[minimax-image] {route_name} key {ki+1}/{n_keys} returned no images")
    return None

def _make_local_fallback():
    """Lazy import local SD client (avoids loading model until needed)."""
    import sd_client
    return sd_client


def _try_minimax_image(prompts, size, sid=None):
    """Generate N preview images via MiniMax (concurrently).

    Per-prompt behavior: try every key. If all keys fail for a given prompt,
    append a None slot instead of bailing the whole batch so partial outages
    don't kill a customer's flow. Caller decides what to do with empty slots
    (typically top up from jojo / local SD).
    """
    if not MINIMAX_IMAGE_KEYS:
        return None
    n_total = len(prompts)
    t0 = time.time()
    print(f"[api_image] trying minimax image ({n_total} prompts, {len(MINIMAX_IMAGE_KEYS)} keys)")
    from concurrent.futures import ThreadPoolExecutor

    def one(idx_p):
        i, p = idx_p
        if sid:
            _pg.Progress(sid, "previews").emit(
                f"minimax-{i+1}/{n_total}", int(i / n_total * 90),
                f"正在生成第 {i+1}/{n_total} 张预览…")
        res = _minimax_image_call(p, n=1, size=size, timeout=150, sid=sid)
        if not res:
            return (None, f"minimax#fail{i+1}")
        return (res[0], f"minimax#{i+1}")

    with ThreadPoolExecutor(max_workers=min(4, n_total)) as ex:
        results = list(ex.map(one, enumerate(prompts)))
    n_ok = sum(1 for b, _ in results if b is not None)
    if n_ok == 0:
        print(f"[api_image] minimax ALL FAILED (+{time.time()-t0:.1f}s)")
        return None
    if n_ok < n_total:
        print(f"[api_image] minimax partial ({n_ok}/{n_total}) (+{time.time()-t0:.1f}s)")
    else:
        print(f"[api_image] minimax all done (+{time.time()-t0:.1f}s)")
    return results

def _try_aixj_image(prompts, size, sid=None, deadline=None):
    """Generate N preview images via AIXJ (primary), concurrently.

    Each prompt is an independent request, so they run in parallel to keep
    the total wait short (a single gpt-image-2 call takes ~60s).
    """
    if not AIXJ_IMAGE_KEYS:
        return None
    n_total = len(prompts)
    print(f"[api_image] trying aixj image ({n_total} prompts, {len(AIXJ_IMAGE_KEYS)} keys)")
    t0 = time.time()
    from concurrent.futures import ThreadPoolExecutor

    def one(idx_p):
        i, p = idx_p
        if sid:
            _pg.Progress(sid, "previews").emit(
                f"aixj-{i+1}/{n_total}", int(i / n_total * 90),
                f"正在生成第 {i+1}/{n_total} 张预览…")
        res = _aixj_image_call(p, n=1, size=size, timeout=150, sid=sid)
        if not res:
            # The key may have run out of credit while this batch was in
            # flight.  Trying it again only repeats the same error and
            # eats into the budget the next provider needs.
            if not _provider_has_live_key("aixj"):
                print(f"[api_image] aixj prompt {i+1} failed, the key is out of credit")
                return (None, f"aixj#fail{i+1}")
            # transient TLS handshake timeouts happen under concurrency;
            # one retry usually succeeds.  The retry is skipped once the
            # deadline has passed -- otherwise a dead provider burns
            # 90s + 90s per prompt and the frontend gives up first,
            # which is what used to kill the whole chat turn.
            if deadline is not None and time.time() >= deadline:
                print(f"[api_image] aixj prompt {i+1} failed, no budget left for a retry")
                return (None, f"aixj#fail{i+1}")
            print(f"[api_image] aixj prompt {i+1} failed, retrying once")
            res = _aixj_image_call(p, n=1, size=size, timeout=150, sid=sid)
        if not res:
            return (None, f"aixj#fail{i+1}")
        return (res[0], f"aixj#{i+1}")

    with ThreadPoolExecutor(max_workers=min(4, n_total)) as ex:
        results = list(ex.map(one, enumerate(prompts)))
    n_ok = sum(1 for b, _ in results if b is not None)
    if n_ok == 0:
        print(f"[api_image] aixj ALL FAILED (+{time.time()-t0:.1f}s)")
        if sid:
            _pg.Progress(sid, "previews").emit("aixj-dead", 90, "出图服务暂时不可用，正在换一种方式…")
        return None
    if n_ok < n_total:
        print(f"[api_image] aixj partial ({n_ok}/{n_total}) (+{time.time()-t0:.1f}s)")
    else:
        print(f"[api_image] aixj all done (+{time.time()-t0:.1f}s)")
    return results


def _try_jojo_image(prompts, size, sid=None):
    """Generate N preview images via jojo, one after the other.

    jojo is the last cloud backup: its key usually runs out of quota, and
    a dead key must not waste the visitor's time.
    """
    if not JOJO_KEYS:
        return None
    n_total = len(prompts)
    t0 = time.time()
    print(f"[api_image] jojo-image ({n_total} prompts, {len(JOJO_KEYS)} keys)")
    results = []
    for i, p in enumerate(prompts):
        if sid:
            _pg.Progress(sid, "previews").emit(
                f"jojo-{i+1}/{n_total}", int(i / n_total * 90),
                f"正在生成第 {i+1}/{n_total} 张预览…")
        res = _jojo_call(p, n=1, size=size, timeout=60, sid=sid)
        results.append((res[0], f"jojo#{i+1}") if res else (None, f"jojo#fail{i+1}"))
        print(f"[api_image] jojo {i+1}/{n_total} done (+{time.time()-t0:.1f}s)")
    if all(b is None for b, _ in results):
        print(f"[api_image] jojo ALL FAILED (+{time.time()-t0:.1f}s)")
        return None
    return results


def _merge_slots(items, new_items, prefix):
    """Fill None slots in ``items`` (same prompt order) from ``new_items``.

    The k-th None slot maps to the k-th new item; surplus new items are
    dropped -- the caller asked for N images, so handing back N+1 makes the
    frontend render an extra preview and costs another provider call.
    Tags become ``{prefix}#{n}`` so later providers can still recognise
    which slots are already filled.
    """
    none_idx = [k for k, (b, t) in enumerate(items) if b is None]
    for i, (blob, tag) in enumerate(new_items):
        if blob is None:
            continue
        if i < len(none_idx):
            items[none_idx[i]] = (blob, f"{prefix}#{none_idx[i]+1}")
    return items


def _provider_chain(prefer: str) -> list:
    """The order in which the image services are tried.

    ``prefer`` may name one service explicitly; "auto" (the default the
    chat uses) follows the order the operator configured.  The first
    service that is configured and healthy wins, the rest are the automatic
    backup -- the visitor never has to pick a model.

    The default primary is AIXJ (gpt-image-2): the product renders it makes
    are markedly better, and the four prompts are sent in parallel so the
    wait is roughly the same as one call.  MiniMax is the backup -- it has
    two keys and answers in seconds -- and jojo / local-sd are the last
    resorts.  Set ``YXZ_IMAGE_PRIMARY`` to change the order.
    """
    primary = (os.environ.get("YXZ_IMAGE_PRIMARY", "") or "").strip().lower()
    if primary not in ("aixj", "minimax", "jojo"):
        primary = "aixj"

    if prefer in ("auto", "api", "image", "online", ""):
        order = [primary]
    elif prefer in ("aixj", "minimax", "jojo"):
        order = [prefer]
    else:
        order = [primary]

    for name in ("minimax", "aixj", "jojo"):
        if name not in order:
            order.append(name)
    order.append("local")
    return order


def generate_previews(prompts, *, prefer="auto", size="1024x1024", sid=None,
                      budget_s: float = 240.0):
    """Generate previews by walking the provider chain.

    Every service in the chain gets its turn; a service that fails (or only
    answers for some of the pictures) hands the missing slots to the next
    one.  Returns ``(source_label, [(png_bytes or None, tag), ...])``.
    """
    items = []
    deadline = time.time() + max(30.0, float(budget_s or 240.0))
    chain = _provider_chain(prefer)
    labels = {"aixj": "aixj-image", "minimax": "minimax-image",
              "jojo": "jojo-image", "local": "sd-local"}

    for name in chain:
        if name == "local":
            break
        if items and time.time() >= deadline:
            print("[api_image] budget spent, keeping the earlier result")
            return labels.get(chain[0], "image"), items

        # A provider that is known to be down must not be dialled at all.
        # Calling it anyway costs a dozen seconds per picture before the
        # error comes back, and four of those is more than a minute of
        # the visitor watching a frozen bubble.
        if _provider_is_open(name):
            print(f"[api_image] {name} is on cooldown, skipping it")
            continue
        if not _provider_has_live_key(name):
            print(f"[api_image] {name} has no usable key left, skipping it")
            continue

        if name == "aixj":
            m = _try_aixj_image(prompts, size, sid=sid, deadline=deadline)
        elif name == "minimax":
            m = _try_minimax_image(prompts, size, sid=sid)
        else:
            m = _try_jojo_image(prompts, size, sid=sid)

        if m is None:
            print(f"[api_image] {name} unavailable, trying the next service")
            continue

        if items:
            _merge_slots(items, m, name)
        else:
            items.extend(m)

        if all(b is not None for b, _ in items):
            return labels.get(name, "image"), items

        if sid:
            _pg.Progress(sid, "previews").emit(
                f"{name}-partial", 70, "部分预览还没生成好，正在补齐…")
        print(f"[api_image] {name} partial, topping up the missing pictures")

    # Local SD is the last resort and it is not even bundled in the release
    # build.  It may only run when the cloud services produced nothing at
    # all -- a partial result is far better than a crash.
    if "local" in chain and not items:
        print(f"[api_image] generating {len(prompts)} via local SD 1.5")
        sd = _make_local_fallback()
        seed_base = 42
        n_total = len(prompts)
        from io import BytesIO
        for idx in range(len(items)):
            if items[idx][0] is None:
                try:
                    results = sd.generate(prompts[idx], n=1, seed=seed_base + idx)
                except Exception as e:
                    print(f"[api_image] local SD fill idx={idx} failed: {e}")
                    continue
                if results:
                    img, seed_used = results[0]
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    items[idx] = (buf.getvalue(), f"sd#{seed_used}")
        for i in range(len(items), n_total):
            try:
                results = sd.generate(prompts[i], n=1, seed=seed_base + i)
            except Exception as e:
                print(f"[api_image] local SD idx={i} failed: {e}")
                items.append((None, f"sd#fail{i+1}"))
                continue
            if not results:
                items.append((None, f"sd#fail{i+1}"))
                continue
            img, seed_used = results[0]
            buf = BytesIO()
            img.save(buf, format="PNG")
            items.append((buf.getvalue(), f"sd#{seed_used}"))
            if sid:
                pct = int((i + 1) / n_total * 90)
                _pg.Progress(sid, "previews").emit(f"sd-{i+1}/{n_total}", pct, f"正在生成第 {i+1}/{n_total} 张预览…")
        return "sd-local", items

    if items:
        print("[api_image] keeping the partial result from the cloud services")
        return labels.get(chain[0], "image"), items

    print(f"[api_image] no provider matched prefer={prefer}; returning empty")
    return "none", items


def health():
    return {
        "aixj_image_key_loaded": bool(AIXJ_IMAGE_KEY),
        "aixj_image_keys": len(AIXJ_IMAGE_KEYS),
        "aixj_dead_keys": len(_AIXJ_DEAD_KEYS),
        "jojo_dead_keys": len(_JOJO_DEAD_KEYS),
        "jojo_alive_keys": max(0, len(JOJO_KEYS) - len(_JOJO_DEAD_KEYS)),
        "jojo_key_loaded": bool(JOJO_KEY),
        "jojo_key_preview": (JOJO_KEY[:14] + "...") if JOJO_KEY else None,
        "minimax_image_keys": len(MINIMAX_IMAGE_KEYS),
        "minimax_dead_keys": len(_MINIMAX_DEAD_KEYS),
        "minimax_alive_keys": max(0, len(MINIMAX_IMAGE_KEYS) - len(_MINIMAX_DEAD_KEYS)),
        "minimax_image_model": MINIMAX_H3_MODEL,
        "chain": " > ".join(
            f"{name}-image" for name in _provider_chain("auto") if name != "local"
        ) + " > local-sd",
    }


# ---------------------------------------------------------------------------
# Reference-image refinement ("按批注修改一版")
# ---------------------------------------------------------------------------
_DL_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

def _build_multipart(fields: dict, image_bytes: bytes, filename: str) -> tuple[bytes, str]:
    """Build a multipart/form-data body (model + prompt fields, one image file)."""
    import uuid
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            ("--" + boundary + "\r\n"
             f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
             + str(value) + "\r\n").encode("utf-8")
        )
    parts.append(
        ("--" + boundary + "\r\n"
         f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
         "Content-Type: image/png\r\n\r\n").encode("utf-8")
        + image_bytes + b"\r\n"
    )
    parts.append(("--" + boundary + "--\r\n").encode("utf-8"))
    return b"".join(parts), boundary


def refine_preview(reference: bytes, instruction: str, *, sid=None, timeout=150.0):
    """Edit an existing preview image following a Chinese instruction.

    Chain: MiniMax H3-Image ``/v1/images/edits`` -> MiniMax image-01 with
    ``subject_reference`` -> AIXJ gpt-image-2 ``/images/edits`` -> None if
    everything fails.

    Returns (png_bytes, tag) or raises RuntimeError with a readable message.
    """
    if not instruction.strip():
        raise RuntimeError("修改指令不能为空")
    if not AIXJ_IMAGE_KEYS and not MINIMAX_IMAGE_KEYS:
        raise RuntimeError("没有可用的生图服务（aixj 图片 key 未配置）")

    prompt = instruction.strip()

    # MiniMax keeps the picture as the subject of the new design.
    if MINIMAX_IMAGE_KEYS:
        try:
            out = _minimax_image_call(
                prompt, n=1, size="1024x1024", timeout=150, sid=sid,
                reference=reference,
            )
            if out:
                if sid:
                    _pg.Progress(sid, "previews").emit("refine-done", 100, "AI 已按批注修改完成")
                return out[0], "minimax-image-ref"
        except Exception as e:
            print(f"[api_image] minimax refine failed: {e}", flush=True)

    n_keys = len(AIXJ_IMAGE_KEYS)
    last_err = "aixj 生图服务暂时不可用"
    for ki, key in enumerate(AIXJ_IMAGE_KEYS):
        if key in _AIXJ_DEAD_KEYS:
            continue
        if sid:
            _pg.Progress(sid, "previews").emit(
                "refine-trying", 8, "AI 正在按批注修改设计稿…")
        try:
            small = _prepare_reference(reference) or reference
            body = json.dumps({
                "model": AIXJ_IMAGE_MODEL,
                "prompt": prompt,
                "size": "1024x1024",
                "response_format": "b64_json",
                "images": [{
                    "image_url": "data:image/jpeg;base64,"
                                + base64.b64encode(small).decode(),
                }],
            }).encode("utf-8")
            req = urllib.request.Request(
                AIXJ_BASE + "/images/edits",
                data=body, method="POST",
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = json.loads(r.read().decode("utf-8", "ignore"))
            out = None
            for item in payload.get("data") or []:
                if item.get("b64_json"):
                    out = base64.b64decode(item["b64_json"])
                    break
                url = item.get("url")
                if url:
                    blob = _download_with_retry(url, ua=_DL_UA, timeout=30.0)
                    if blob:
                        out = blob
                        break
            if not out:
                last_err = f"aixj key {ki+1}/{n_keys} 未返回图片"
                continue
            if out:
                if sid:
                    _pg.Progress(sid, "previews").emit("refine-done", 100, "AI 已按批注修改完成")
                return out, "aixj-image"
            last_err = f"aixj key {ki+1}/{n_keys} 下载失败"
        except urllib.error.HTTPError as e:
            try:
                err = e.read().decode("utf-8", "ignore")
            except Exception:
                err = str(e.reason)
            low = err.lower()
            if e.code in (401, 402, 403) or any(
                x in low for x in ("quota", "balance", "insufficient")
            ) or "invalid" in low:
                _AIXJ_DEAD_KEYS.add(key)
                print(f"[api_image] refine key {ki+1}/{n_keys} DEAD (HTTP {e.code}): {err[:120]}", flush=True)
                continue
            last_err = f"aixj key {ki+1}/{n_keys} HTTP {e.code}: {err[:160]}"
            print(f"[api_image] {last_err}", flush=True)
        except Exception as e:
            last_err = f"aixj key {ki+1}/{n_keys} {type(e).__name__}: {str(e)[:160]}"
            print(f"[api_image] {last_err}", flush=True)
    raise RuntimeError(last_err)


def edit_previews(reference: bytes, prompts, *, sid=None, timeout=120.0):
    """Turn one uploaded picture into several product views.

    The picture is the shape reference and the prompt says what the visitor
    wants done with it ("make it a blue robot lamp" and so on).

    Two routes can keep the picture:
      1. MiniMax ``MiniMax-H3-Image`` on ``/v1/images/edits`` -- the picture
         travels with the request and the prompt says what should become
         of it (the older ``image-01`` line with ``subject_reference``
         covers it when H3 is unavailable).
      2. AIXJ ``/images/edits`` -- the relay wants a JSON body with
         ``images: [{"image_url": ...}]``, not a multipart upload.

    Whichever route answers first wins; a provider that fails leaves its
    slot empty so the caller can still fall back to plain rendering.

    Returns a list of ``(png_bytes_or_None, tag)``, one per prompt.
    """
    if not reference:
        raise RuntimeError("没有参考图片")
    prompts = list(prompts or [])
    if not prompts:
        raise RuntimeError("没有生成提示词")

    results = []
    last_err = "图生图服务暂时不可用"
    for pi, prompt in enumerate(prompts):
        if sid:
            _pg.Progress(sid, "previews").emit(
                "edit-trying", 8 + pi * 8, f"正在按你的图片生成第 {pi + 1}/{len(prompts)} 张设计稿…")
        blob = None
        tag = "image-to-image-fail"

        # -- route 1: MiniMax subject_reference -------------------------
        if MINIMAX_IMAGE_KEYS:
            try:
                out = _minimax_image_call(
                    # Image generation with a reference picture takes
                    # noticeably longer than a plain one (the reference is
                    # uploaded and re-rendered): 60s was short enough to
                    # time out on a busy link and throw away a picture
                    # that was about to arrive.
                    prompt, n=1, size="1024x1024", timeout=150, sid=sid,
                    reference=reference,
                )
                if out:
                    blob = out[0]
                    tag = "minimax-image-ref"
            except Exception as e:
                print(f"[api_image] minimax subject_reference failed: {e}", flush=True)

        # -- route 2: AIXJ /images/edits -------------------------------
        if blob:
            results.append((blob, tag))
            continue

        n_keys = len(AIXJ_IMAGE_KEYS)
        for ki, key in enumerate(AIXJ_IMAGE_KEYS):
            if key in _AIXJ_DEAD_KEYS:
                continue
            try:
                small = _prepare_reference(reference) or reference
                body = json.dumps({
                    "model": AIXJ_IMAGE_MODEL,
                    "prompt": prompt,
                    "size": "1024x1024",
                    "response_format": "b64_json",
                    "images": [{
                        "image_url": "data:image/jpeg;base64,"
                                    + base64.b64encode(small).decode(),
                    }],
                }).encode("utf-8")
                req = urllib.request.Request(
                    AIXJ_BASE + "/images/edits",
                    data=body, method="POST",
                    headers={
                        "Authorization": "Bearer " + key,
                        "Content-Type": "application/json",
                    },
                )
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    payload = json.loads(r.read().decode("utf-8", "ignore"))
                for item in payload.get("data") or []:
                    if item.get("b64_json"):
                        blob = base64.b64decode(item["b64_json"])
                        tag = "aixj-image"
                        break
                    url = item.get("url")
                    if url:
                        data = _download_with_retry(url, ua=_DL_UA, timeout=30.0)
                        if data:
                            blob = data
                            tag = "aixj-image"
                            break
                if blob:
                    break
                last_err = f"aixj key {ki+1}/{n_keys} 未返回图片"
            except urllib.error.HTTPError as e:
                try:
                    err = e.read().decode("utf-8", "ignore")
                except Exception:
                    err = str(e.reason)
                low = err.lower()
                # Only a quota / auth problem kills the key.  The relay also
                # answers "invalid" for a payload it does not like (it
                # wants a public image URL, not a data URL), and that has
                # nothing to do with the key being usable for plain
                # generation -- blacklisting it there took the whole image
                # service down for the rest of the session.
                if e.code in (401, 402, 403) or any(
                    x in low for x in ("quota", "balance", "insufficient")
                ):
                    _AIXJ_DEAD_KEYS.add(key)
                    print(f"[api_image] edit key {ki+1}/{n_keys} DEAD (HTTP {e.code}): {err[:120]}", flush=True)
                    continue
                last_err = f"aixj key {ki+1}/{n_keys} HTTP {e.code}: {err[:160]}"
                print(f"[api_image] {last_err}", flush=True)
            except Exception as e:
                last_err = f"aixj key {ki+1}/{n_keys} {type(e).__name__}: {str(e)[:160]}"
                print(f"[api_image] {last_err}", flush=True)
        results.append((blob, tag))
    if all(blob is None for blob, _ in results):
        raise RuntimeError(last_err)
    return results


if __name__ == "__main__":
    h = health()
    print("health:", h)
    src, items = generate_previews([
        "cute cartoon dragon mascot, single object, white background, 3d-print friendly, soft colors",
        "cute cartoon dragon mascot, three-quarter view, vinyl toy finish, white background",
    ])
    print(f"source={src} count={len(items)}")
    for b, tag in items:
        print(f"  {tag}: {len(b)} bytes")


