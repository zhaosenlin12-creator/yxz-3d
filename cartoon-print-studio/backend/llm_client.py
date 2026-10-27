"""LLM adapter for Cartoon Print Studio.

Provides prompt rewriting / idea elaboration for the AI thinking pipeline.
- Primary:   MiniMax LLM (api.minimaxi.com, native v2 endpoint)
- Secondary: DeepSeek (api.deepseek.com, OpenAI-compatible)
- Fallback (always-on): rule-based prompt elaborator

Keys are read from <install>/keys.txt (or ~/Desktop/key.txt) and classified
by line label so a deepseek/aixj/jojo key is never sent to MiniMax:
  minimax-key / minimax-key-2 / sk-cp-...  -> MiniMax
  deepseek-key / deepseek api             -> DeepSeek
"""
from __future__ import annotations
import json, os, re, time, urllib.request, urllib.error
from dataclasses import dataclass
from typing import List, Optional, Tuple

# MiniMax native v2 endpoint. NOTE: must be api.minimaxi.com — the .chat
# variant returns 2049 invalid api key for the same credentials.
MINIMAX_ENDPOINTS = ["https://api.minimaxi.com/v1/text/chatcompletion_v2"]
MINIMAX_API_KEYS = [os.environ.get("MINIMAX_API_KEY", "").strip()]

DEEPSEEK_ENDPOINTS = ["https://api.deepseek.com/chat/completions"]
DEEPSEEK_API_KEYS = [os.environ.get("DEEPSEEK_API_KEY", "").strip()]
DEEPSEEK_MODEL = "deepseek-chat"

# Prefer <install>/keys.txt, fall back to ~/Desktop/key.txt (Windows convenience)
_ROOT = os.environ.get("CARTOON_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_KEYFILE = (
    os.path.join(_ROOT, "keys.txt")
    if os.path.isfile(os.path.join(_ROOT, "keys.txt"))
    else os.path.expanduser(r"~\Desktop\key.txt")
)


def _classify_keys_from_file():
    """Parse keys.txt and fill MINIMAX_API_KEYS / DEEPSEEK_API_KEYS by label.

    Labels understood (case-insensitive, supports ':' or '：'):
      minimax* / sk-cp-...            -> MiniMax
      deepseek*                       -> DeepSeek
    Keys without a label that look like sk-cp- go to MiniMax as before.
    Labels that mark an image provider (contains 'image' / '生图') are
    skipped: an image key must never be sent to a chat endpoint.
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
                tag in low for tag in ("minimax", "deepseek")):
            continue
        key = None
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
        # 生图 provider 的 key（aixj / minimax-image / jojo-image …）绝不能
        # 发到对话端点，否则只会拿到 1004/401 白跑一次。
        if "image" in label or "生图" in label:
            continue
        if "deepseek" in (label or "") or (not label and key.startswith("sk-f")):
            if key not in DEEPSEEK_API_KEYS:
                DEEPSEEK_API_KEYS.append(key)
        elif "minimax" in (label or "") or key.startswith("sk-cp-"):
            if key not in MINIMAX_API_KEYS:
                MINIMAX_API_KEYS.append(key)


_classify_keys_from_file()

# Strip empties
MINIMAX_API_KEYS = [k for k in MINIMAX_API_KEYS if k]
DEEPSEEK_API_KEYS = [k for k in DEEPSEEK_API_KEYS if k]


def _call_openai_style(url, body, key, timeout, deadline=None):
    """POST an OpenAI-compatible chat request. Returns text or None."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    attempt_timeout = timeout
    if deadline is not None:
        attempt_timeout = max(1.0, min(timeout, deadline - time.time()))
        if attempt_timeout < 1.0:
            return None
    try:
        with urllib.request.urlopen(req, timeout=attempt_timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return None  # key rejected
        try:
            err = e.read().decode("utf-8", "ignore")
        except Exception:
            err = ""
        # quota / balance exhausted -> abandon this key, not the chain
        if "quota" in err.lower() or "balance" in err.lower() or e.code == 429:
            return None
        return None
    except Exception:
        return None
    return _extract_openai_text(payload)


def _extract_openai_text(payload):
    choices = payload.get("choices") or []
    for c in choices:
        msg = c.get("message") or {}
        content = (msg.get("content") or "").strip()
        if content:
            return content
    return None


def _minimax_call(prompt, *, model="MiniMax-Text-01", max_retries=1, timeout=20, deadline=None):
    """Call the MiniMax chat API (native v2 endpoint, api.minimaxi.com).

    ``deadline`` is an absolute ``time.time()`` value: when it passes, the
    remaining keys and retries are skipped so an unreachable provider can
    never hold a request open longer than the caller allowed.
    """
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an art director for a kid-friendly 3D-print shop. Reply in JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
        "max_tokens": 1024,
    }
    data = json.dumps(body).encode("utf-8")
    for key in MINIMAX_API_KEYS:
        if not key:
            continue
        for ep in MINIMAX_ENDPOINTS:
            for attempt in range(max_retries + 1):
                if deadline is not None and time.time() >= deadline:
                    return None
                attempt_timeout = timeout
                if deadline is not None:
                    attempt_timeout = max(1.0, min(timeout, deadline - time.time()))
                try:
                    req = urllib.request.Request(
                        ep, data=data, method="POST",
                        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req, timeout=attempt_timeout) as r:
                        payload = json.loads(r.read().decode("utf-8", "ignore"))
                except urllib.error.HTTPError as e:
                    if e.code in (401, 403):
                        break
                    # quota / rate-limit (429 / 2056) -> try next key
                    if e.code == 429:
                        break
                    continue
                except Exception:
                    continue
                base = payload.get("base_resp", {}) or {}
                if base.get("status_code", 0) != 0:
                    code = base.get("status_code")
                    # invalid key / quota / not allowed -> abandon this key
                    if code in (2049, 1004, 1002, 2056):
                        break
                    continue
                reply = payload.get("reply", "")
                if not reply and payload.get("choices"):
                    reply = _extract_openai_text(payload)
                if reply:
                    return reply.strip()
    return None


def _deepseek_call(prompt, *, model=DEEPSEEK_MODEL, timeout=20, deadline=None):
    """Call DeepSeek chat (OpenAI-compatible). Returns text or None."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are an art director for a kid-friendly 3D-print shop. Reply in JSON only."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.9,
        "max_tokens": 1024,
    }
    for key in DEEPSEEK_API_KEYS:
        if not key:
            continue
        for ep in DEEPSEEK_ENDPOINTS:
            reply = _call_openai_style(ep, body, key, timeout, deadline)
            if reply:
                return reply.strip()
    return None


def llm_call(prompt, *, timeout=20, deadline=None, max_retries=1):
    """Try MiniMax -> DeepSeek. Returns (text, provider) or (None, None)."""
    if deadline is None:
        deadline = time.time() + max(timeout, 1) * 2 + 5
    t0 = time.time()
    if MINIMAX_API_KEYS:
        reply = _minimax_call(prompt, max_retries=max_retries, timeout=timeout, deadline=deadline)
        if reply:
            return reply, "MiniMax"
    if DEEPSEEK_API_KEYS and time.time() < deadline:
        reply = _deepseek_call(prompt, timeout=timeout, deadline=deadline)
        if reply:
            return reply, "DeepSeek"
    return None, None


def has_provider() -> bool:
    return any(MINIMAX_API_KEYS) or any(DEEPSEEK_API_KEYS)


def key_counts() -> dict:
    return {
        "minimax_llm_keys": len(MINIMAX_API_KEYS),
        "deepseek_llm_keys": len(DEEPSEEK_API_KEYS),
    }


POSE_VARIANTS = [
    ("front-facing standing pose, both arms relaxed", "正面站姿"),
    ("three-quarter view, friendly posture", "3/4 侧视"),
    ("playful action pose mid-jump or waving", "动态姿势"),
    ("sitting pose, calm happy face", "坐姿"),
    ("chibi close-up with oversized head and big eyes", "Q 版大头"),
]

STYLE_VARIANTS = [
    "soft pastel cel-shaded cartoon, gentle inner shadow, no texture noise",
    "chunky vinyl toy finish, smooth rounded shapes",
    "slightly hand-painted storybook style, soft brush, dreamy mood",
]

KID_HINTS = re.compile(
    r"(宝宝|小[朋友孩]|童|kid|child|gift|礼物|送[给到]|可爱|cute|卡通|萌|q版|chibi)",
    re.IGNORECASE,
)


@dataclass
class PreviewSpec:
    pose: str
    style: str
    sub_prompt: str
    caption: str


def _extract_keywords(prompt):
    raw = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-]*", prompt)
    out = []
    seen = set()
    stop = {
        "a", "an", "the", "of", "for", "to", "and", "with", "is", "i", "want",
        "make", "create", "give", "please", "做", "一个", "我想", "的", "帮我", "请", "和", "给",
    }
    for w in raw:
        wl = w.lower()
        if wl in seen or wl in stop:
            continue
        seen.add(wl)
        out.append(w)
    return out[:12]


def _noun_phrase(prompt):
    s = prompt.strip().strip(",").strip()
    # strip leading request verbs (zh + en)
    s = re.sub(r"^(请|麻烦|帮我)?(做个|做一个|做|做一只|我要|我想|给你?)[\s,，]?", "", s)
    s = re.sub(r"^(please\s+)?(make|create|give me|i want|i would like)\s+", "", s, flags=re.IGNORECASE)
    # strip trailing context: 送给 X / 给 X / for X / as a gift / for my kid ...
    s = re.sub(r"[\s,，]*(送[给到][\u4e00-\u9fff]{1,5}|给[\u4e00-\u9fff]{1,5}|for\s+\w+|as\s+a?\s*(gift|present|toy)|for\s+my\s+\w+)\s*$", "", s, flags=re.IGNORECASE)
    return s.strip().strip(",").strip(".").strip()


def elaborate_via_llm(user_prompt, n=6):
    user = (
        f"Customer request: {user_prompt!r}\n\nProduce exactly {n} image prompts as JSON:\n"
        "Format: {\"items\":[{\"pose\":\"...\",\"style\":\"...\",\"prompt\":\"...\",\"caption\":\"...\"}}, ...]}\n"
        "Each prompt: subject + pose + style + white background no text single object full body.\n"
        "Captions 2-6 words for UI chip."
    )
    text, provider = llm_call(user, timeout=20, deadline=time.time() + 40)
    if not text:
        return None
    text = text.strip().strip("`").strip()
    if text.startswith("json"):
        text = text[4:].strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    items = data.get("items") or []
    out = []
    for it in items[:n]:
        p = (it.get("prompt") or "").strip()
        if not p:
            continue
        out.append(PreviewSpec(
            it.get("pose", "").strip(),
            it.get("style", "").strip(),
            p,
            it.get("caption", "").strip() or "选项",
        ))
    return out if out else None


def elaborate_local(user_prompt, n=6):
    subject = _noun_phrase(user_prompt) or "mascot character"
    keywords = _extract_keywords(user_prompt)
    is_kid = bool(KID_HINTS.search(user_prompt)) or "kid" in user_prompt.lower()
    base_style = STYLE_VARIANTS[0] if is_kid else STYLE_VARIANTS[2]
    suffix = "white background, no text, single object, full body, kid-friendly soft palette"
    out = []
    n = max(2, min(n, len(POSE_VARIANTS)))
    for i in range(n):
        pose, label = POSE_VARIANTS[i % len(POSE_VARIANTS)]
        style = base_style if i % 2 == 0 else STYLE_VARIANTS[(i // 2) % len(STYLE_VARIANTS)]
        sub_prompt = f"{subject}, {pose}, {style}, {suffix}, 3d printable figurine, clean silhouette"
        out.append(PreviewSpec(pose, style, sub_prompt, f"{label} · 风格{i+1}"))
    for i, kw in enumerate(keywords[:n]):
        out[i % len(out)].sub_prompt += f", accent: {kw}"
    return out


def polish_prompt_local(user_prompt: str) -> str:
    """Rule-based prompt polish used when no LLM provider is reachable.

    The subject, colours and explicit requirements of the user are kept; the
    rules only append the details a single, printable object needs. Nothing
    is sent anywhere, so this stays usable without a configured provider.
    """
    text = " ".join(str(user_prompt or "").split()).strip()
    if not text:
        return text
    subject = text.rstrip("。.!！?？,，、 ")
    clauses = []
    if not re.search(r"(背景|background|纯色|solid)", subject, re.IGNORECASE):
        clauses.append("纯白背景，无其它物体")
    if not re.search(r"(卡通|cartoon|chibi|q版|手绘|绘本|写实|realistic)", subject, re.IGNORECASE):
        clauses.append("卡通风格，造型圆润饱满")
    if not re.search(r"(材质|material|塑料|树脂|陶|金属|光滑)", subject, re.IGNORECASE):
        clauses.append("表面平整光滑，无细碎纹理")
    if not re.search(r"(完整|全身|正面|居中|full body|centered)", subject, re.IGNORECASE):
        clauses.append("主体完整居中，单一物体")
    if not clauses:
        return subject
    return f"{subject}，{'，'.join(clauses)}"


def elaborate(user_prompt, n=6, *, think_budget_ms=0):
    info = {"model": None, "source": None, "elapsed_ms": 0,
            "fallback_reason": None, "thinking": []}
    t0 = time.time()
    info["thinking"].append("收到需求，开始分析主体、风格与目标人群")
    specs = None
    if has_provider():
        info["thinking"].append("询问大模型生成差异化变体")
        specs = elaborate_via_llm(user_prompt, n)
        if specs is not None:
            info["model"] = "LLM"
            info["source"] = "llm"
            info["elapsed_ms"] = int((time.time() - t0) * 1000)
            info["thinking"].append(f"LLM 返回 {len(specs)} 个候选")
            return specs, "llm", info
        info["fallback_reason"] = "llm_unreachable_or_rejected"
        info["thinking"].append("LLM 不可达，转本地规则增强")
    specs = elaborate_local(user_prompt, n)
    info["source"] = "local"
    info["elapsed_ms"] = int((time.time() - t0) * 1000)
    info["thinking"].append(f"基于规则生成 {len(specs)} 个候选（不同姿势/视角/画风）")
    return specs, "local", info


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "一只穿橙色披风的蓝色卡通小英雄"
    specs, src, info = elaborate(p, n=4)
    print(f"[source={src}] {info}")
    for s in specs:
        print(f"- {s.caption}: {s.sub_prompt[:120]}")
