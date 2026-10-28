"""Microsoft Edge free neural TTS, used as the last speech fallback.

The Edge "read aloud" voices are free and need no API key, but they live
behind a websocket endpoint that the ``edge-tts`` package talks to. The
package is optional: when it is missing (or Microsoft is unreachable) the
endpoints report that the voice pack is unavailable instead of failing the
whole request, so the frontend can fall through to the next provider.

This is deliberately *not* the browser's own ``speechSynthesis``. That one
uses whatever the operating system happens to expose and sounds flat; the
Edge neural voices are the same ones Edge reads articles with.
"""

from __future__ import annotations

import asyncio
import base64
import io
import re
from typing import Any, Dict, List, Optional

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "+0Hz"
DEFAULT_VOLUME = "+0%"

# Only the languages 宜小智 actually speaks are worth offering. The full Edge
# catalogue has 300+ voices; listing them all would bury the useful ones.
WANTED_LOCALES = ("zh-CN", "zh-HK", "zh-TW", "en-US", "en-GB")

# The Edge voices refuse to speak a text that carries no pronounceable
# character ("。" or "？"), and answer with "No audio was received". That is a
# normal part of a sentence stream rather than a broken service, so such a
# request gets this 200 ms of silence back: the caller still receives a valid
# mp3 and the speech chain does not have to fall over to a worse voice.
SILENCE_MP3_BASE64 = (
    "SUQzBAAAAAAAIlRTU0UAAAAOAAADTGF2ZjYzLjEuMTAwAAAAAAAAAAAAAAD/84TAAAAAAAAAAAAA"
    "SW5mbwAAAA8AAAALAAAByAB5eXl5eXl5eXmGhoaGhoaGhoaUlJSUlJSUlJShoaGhoaGhoaGvr6+v"
    "r6+vr6+8vLy8vLy8vLzKysrKysrKysrX19fX19fX19fl5eXl5eXl5eXy8vLy8vLy8vL/////////"
    "//8AAAAATGF2YzYzLjEuAAAAAAAAAAAAAAAAJAPAAAAAAAAAAcg+4ITzAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAD/8xTEAAAAA0gAAAAATEFNRTMuMTAwVVX/8xTECwAAA0gAAAAAVVVVVVVVVVVVVVX/"
    "8xTEFgAAA0gAAAAAVVVVVVVVVVVVVVX/8xTEIQAAA0gAAAAAVVVVVVVVVVVVVVX/8xTELAAAA0gA"
    "AAAAVVVVVVVVVVVVVVX/8xTENwAAA0gAAAAAVVVVVVVVVVVVVVX/8xTEQgAAA0gAAAAAVVVVVVVV"
    "VVVVVVX/8xTETQAAA0gAAAAAVVVVVVVVVVVVVVX/8xTEWAAAA0gAAAAAVVVVVVVVVVVVVVX/8xTE"
    "YwAAA0gAAAAAVVVVVVVVVVVVVVX/8xTEbgAAA0gAAAAAVVVVVVVVVVVVVVU="
)
SILENCE_MP3 = base64.b64decode(SILENCE_MP3_BASE64)

# Letters, digits and CJK / kana characters are pronounceable; punctuation
# alone is not.
SPEAKABLE_RE = re.compile(r"[0-9A-Za-z\u00c0-\u024f\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")

_voice_cache: List[Dict[str, Any]] = []
_voice_cache_at = 0.0
VOICE_CACHE_TTL_S = 3600.0


def _edge_tts_module():
    try:
        import edge_tts  # noqa: F401
        return edge_tts
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError("Edge 语音包不可用：缺少 edge-tts 组件") from exc


def _describe(voice: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": voice.get("ShortName", ""),
        "name": voice.get("FriendlyName", voice.get("ShortName", "")),
        "locale": voice.get("Locale", ""),
        "gender": voice.get("Gender", ""),
        "description": f"Microsoft Edge 在线语音：{voice.get('FriendlyName', '')}",
    }


async def list_voices() -> List[Dict[str, Any]]:
    """The Edge voices that 宜小智 can pick, newest first."""
    global _voice_cache, _voice_cache_at

    import time
    now = time.time()
    if _voice_cache and now - _voice_cache_at < VOICE_CACHE_TTL_S:
        return _voice_cache

    edge_tts = _edge_tts_module()
    try:
        raw = await edge_tts.list_voices()
    except Exception as exc:
        raise RuntimeError(f"Edge 语音包不可用：{exc}") from exc

    wanted = []
    for locale in WANTED_LOCALES:
        wanted.extend(v for v in raw if v.get("Locale", "").startswith(locale))
    # Keep the catalogue stable but bounded.
    _voice_cache = [_describe(v) for v in wanted][:60]
    _voice_cache_at = now
    return _voice_cache


async def synthesize(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: str = DEFAULT_RATE,
    pitch: str = DEFAULT_PITCH,
    volume: str = DEFAULT_VOLUME,
) -> bytes:
    """Render ``text`` with an Edge neural voice and return mp3 bytes."""
    content = (text or "").strip()
    if not content:
        return b""

    if not SPEAKABLE_RE.search(content):
        # Nothing pronounceable in there: hand back silence instead of an
        # error, so a punctuation-only fragment does not knock the whole
        # speech chain down to a worse voice.
        return SILENCE_MP3

    edge_tts = _edge_tts_module()
    communicator = edge_tts.Communicate(
        content,
        voice or DEFAULT_VOICE,
        rate=rate or DEFAULT_RATE,
        pitch=pitch or DEFAULT_PITCH,
        volume=volume or DEFAULT_VOLUME,
    )

    buffer = io.BytesIO()
    async for chunk in communicator.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            buffer.write(chunk["data"])

    data = buffer.getvalue()
    if not data:
        raise RuntimeError("Edge 语音包没有返回音频")
    return data


def synthesize_sync(text: str, **kwargs: Any) -> bytes:
    """Blocking helper for callers that are not inside an event loop."""
    return asyncio.run(synthesize(text, **kwargs))

