"""Local speech recognition (语音输入) for 宜小智.

The browser's own ``SpeechRecognition`` is deliberately not used here.
Chrome implements it by streaming the microphone to Google's servers, so a
single dropped packet, a captive Wi-Fi page or a machine that is simply
offline makes the button stop working -- which is exactly the "偶尔能用
偶尔不能用" behaviour this module replaces.

Instead the page records a short clip with ``MediaRecorder`` and posts the
bytes here.  The clip is decoded locally (PyAV, with a plain WAV fast
path) and transcribed by faster-whisper running on the CPU of the very
machine that serves the app: no API key, no quota, no network, and the
same answer on every computer in the room.

The model files live under ``cartoon-print-studio/models/asr`` and are
downloaded once (through the China mirror when one is reachable).  They
are big enough that they are shipped with the release package rather
than committed to git.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

SAMPLE_RATE = 16000

DEFAULT_MODEL_NAME = os.environ.get("YXZ_ASR_MODEL", "small")
# 宜小智 is a Chinese product and the students talk to it in Mandarin.
# Naming the language up front is both faster (whisper does not have to
# detect it) and more accurate; the endpoint still accepts ?language=en
# (or ?language=auto) for the rare case somebody speaks another language.
DEFAULT_LANGUAGE = os.environ.get("YXZ_ASR_LANGUAGE", "zh")
MODEL_ROOT = Path(
    os.environ.get(
        "YXZ_ASR_MODEL_DIR",
        str(Path(__file__).resolve().parent.parent / "models" / "asr"),
    )
)

# Whisper works best with a couple of seconds of context; this nudges it
# towards Mandarin without forcing the language, so an English sentence is
# still recognised correctly.
INITIAL_PROMPT = "以下是宜小智工作台里的一段普通话对话。"

# Below this RMS a clip is treated as silence.  Whisper is happy to invent
# a sentence out of pure noise, which is worse than saying nothing.
SILENCE_RMS = 0.006

_model_lock = threading.Lock()
_model: Any = None
_model_error: Optional[str] = None
_model_name: Optional[str] = None
_load_started = False


def model_dir(name: Optional[str] = None) -> Path:
    return MODEL_ROOT / f"faster-whisper-{name or DEFAULT_MODEL_NAME}"


def _model_present(name: Optional[str] = None) -> bool:
    directory = model_dir(name)
    return (directory / "model.bin").is_file() and (directory / "config.json").is_file()


def _download_model(name: str) -> Optional[Path]:
    """Fetch the whisper weights when they are not on disk yet."""
    directory = model_dir(name)
    if _model_present(name):
        return directory
    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return None

    # The xet backend needs credentials the exhibition machines do not
    # have; plain http downloads through the mirror work everywhere.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    endpoints = [os.environ.get("HF_ENDPOINT", ""), "https://hf-mirror.com", "https://huggingface.co"]
    for endpoint in endpoints:
        if endpoint:
            os.environ["HF_ENDPOINT"] = endpoint
        else:
            os.environ.pop("HF_ENDPOINT", None)
        try:
            snapshot_download(
                f"Systran/faster-whisper-{name}",
                local_dir=str(directory),
                allow_patterns=["*.bin", "*.json", "*.txt"],
            )
            if _model_present(name):
                return directory
        except Exception:
            continue
    return None


def _load_model(name: Optional[str] = None):
    """Load (once) the whisper model used for transcription."""
    global _model, _model_error, _model_name
    wanted = name or DEFAULT_MODEL_NAME
    with _model_lock:
        if _model is not None and _model_name == wanted:
            return _model
        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - depends on the machine
            _model_error = f"缺少 faster-whisper 组件：{exc}"
            return None

        directory = model_dir(wanted)
        if not _model_present(wanted):
            directory = _download_model(wanted)
        if directory is None:
            _model_error = "语音识别模型未安装"
            return None

        try:
            model = WhisperModel(
                str(directory),
                device="cpu",
                compute_type="int8",
                cpu_threads=_thread_count(),
                num_workers=1,
            )
        except Exception as exc:
            _model_error = f"语音识别模型加载失败：{exc}"
            return None
        _model = model
        _model_name = wanted
        _model_error = None
        return _model


def _thread_count() -> int:
    """How many threads whisper should use.

    More threads than physical cores only makes the encoder fight itself,
    so a machine with a lot of logical processors gets half of them.
    """
    logical = os.cpu_count() or 4
    if logical > 8:
        logical = logical // 2
    return max(1, min(8, logical))


def _ensure_model(name: Optional[str] = None):
    """Load the model, downloading it first when it is missing."""
    return _load_model(name)


def warm_up() -> None:
    """Load the model in the background so the first recording is quick."""
    global _load_started
    if _load_started:
        return
    _load_started = True

    def worker():
        try:
            _load_model()
        except Exception:
            pass

    threading.Thread(target=worker, name="yxz-asr-warmup", daemon=True).start()


def status() -> Dict[str, Any]:
    """A cheap description of the local speech recognition stack."""
    name = DEFAULT_MODEL_NAME
    return {
        "ok": _model is not None,
        "engine": "faster-whisper",
        "model": name,
        "model_dir": str(model_dir(name)),
        "model_present": _model_present(name),
        "loaded": _model is not None,
        "loading": _load_started and _model is None,
        "error": _model_error,
        "sample_rate": SAMPLE_RATE,
    }


def _resample(samples: np.ndarray, rate: int) -> np.ndarray:
    """Bring any sample rate down to the 16 kHz whisper expects."""
    if rate == SAMPLE_RATE or samples.size == 0:
        return samples.astype(np.float32)
    target = int(round(samples.size * SAMPLE_RATE / float(rate)))
    if target <= 0:
        return np.zeros(0, dtype=np.float32)
    # Linear interpolation is enough: whisper itself downsamples to the
    # same rate and the audio it gets is 16 kHz speech.
    source_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    target_x = np.linspace(0.0, 1.0, num=target, endpoint=False)
    return np.interp(target_x, source_x, samples).astype(np.float32)


def _decode_wav(data: bytes) -> Optional[np.ndarray]:
    """Decode a RIFF/WAVE file without any third-party help.

    The chunks are read by hand rather than with the ``wave`` module,
    because browsers and encoders write a fair number of flavours of the
    header (extensible headers, 32 bit float samples) that the standard
    library refuses to open.
    """
    try:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        position = 12
        audio_format = 0
        channels = 0
        rate = 0
        bits = 0
        frames = b""
        while position + 8 <= len(data):
            chunk_id = data[position:position + 4]
            size = int.from_bytes(data[position + 4:position + 8], "little")
            position += 8
            body = data[position:position + size]
            if chunk_id == b"fmt " and len(body) >= 16:
                audio_format = int.from_bytes(body[0:2], "little")
                channels = int.from_bytes(body[2:4], "little")
                rate = int.from_bytes(body[4:8], "little")
                bits = int.from_bytes(body[14:16], "little")
                if audio_format == 0xFFFE and len(body) >= 26:
                    # WAVE_FORMAT_EXTENSIBLE: the real format sits in the
                    # first two bytes of the sub-format GUID.
                    audio_format = int.from_bytes(body[24:26], "little")
            elif chunk_id == b"data":
                frames = body
            position += size + (size & 1)
    except Exception:
        return None

    if not frames or channels <= 0 or rate <= 0:
        return None

    if audio_format == 3 and bits == 32:
        samples = np.frombuffer(frames, dtype=np.float32)
    elif audio_format == 3 and bits == 64:
        samples = np.frombuffer(frames, dtype=np.float64).astype(np.float32)
    elif bits == 16:
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif bits == 24:
        raw = np.frombuffer(frames[: len(frames) - len(frames) % 3], dtype=np.uint8).reshape(-1, 3)
        value = (raw[:, 0].astype(np.int32) | (raw[:, 1].astype(np.int32) << 8) | (raw[:, 2].astype(np.int8).astype(np.int32) << 16))
        samples = value.astype(np.float32) / 8388608.0
    elif bits == 32:
        samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif bits == 8:
        samples = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return None

    if channels > 1:
        samples = samples.reshape(-1, channels)[:, 0]
    return _resample(samples, rate)


def _decode_pyav(data: bytes) -> Optional[np.ndarray]:
    """Decode anything the browser can record (webm/opus, mp4/aac, ogg)."""
    try:
        import av
    except Exception:
        return None

    chunks: List[np.ndarray] = []
    try:
        container = av.open(io.BytesIO(data))
    except Exception:
        return None

    try:
        streams = container.streams.audio
        if not streams:
            return None
        resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        for frame in container.decode(streams[0]):
            for out in resampler.resample(frame):
                array = out.to_ndarray()
                if array.ndim > 1:
                    array = array[0]
                chunks.append(array.astype(np.float32) / 32768.0)
        for out in resampler.resample(None):
            array = out.to_ndarray()
            if array.ndim > 1:
                array = array[0]
            chunks.append(array.astype(np.float32) / 32768.0)
    except Exception:
        return None
    finally:
        try:
            container.close()
        except Exception:
            pass

    if not chunks:
        return None
    return np.concatenate(chunks).astype(np.float32)


def _decode_ffmpeg(data: bytes) -> Optional[np.ndarray]:
    """Last resort: the ffmpeg binary, when the machine happens to have it."""
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", path, "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-",
            ],
            capture_output=True,
            timeout=60,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        return samples
    except Exception:
        return None
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass


def decode_audio(data: bytes) -> Optional[np.ndarray]:
    """Turn whatever the browser sent into 16 kHz mono float samples."""
    if not data:
        return None
    samples = _decode_wav(data)
    if samples is None:
        samples = _decode_pyav(data)
    if samples is None:
        samples = _decode_ffmpeg(data)
    if samples is None or samples.size == 0:
        return None
    return samples.astype(np.float32)


def _trim_silence(samples: np.ndarray) -> np.ndarray:
    """Drop the quiet head and tail so whisper does not hallucinate."""
    if samples.size == 0:
        return samples
    window = max(1, int(SAMPLE_RATE * 0.02))
    count = samples.size // window
    if count < 1:
        return samples
    frames = samples[: count * window].reshape(count, window)
    energy = np.sqrt((frames ** 2).mean(axis=1))
    loud = np.nonzero(energy > SILENCE_RMS)[0]
    if loud.size == 0:
        # Nothing but room noise: whisper would happily invent a sentence
        # out of it, so the clip is reported as silence instead.
        return np.zeros(0, dtype=np.float32)
    start = max(0, int(loud[0]) * window - window * 5)
    end = min(samples.size, int(loud[-1]) * window + window * 5)
    return samples[start:end]


def transcribe(data: bytes, *, model: Optional[str] = None, language: Optional[str] = None) -> Dict[str, Any]:
    """Transcribe a recorded clip and return the recognised text."""
    started = time.time()
    samples = decode_audio(data)
    if samples is None or samples.size == 0:
        raise RuntimeError("无法解析这段录音，请重新录制一次")

    trimmed = _trim_silence(samples)
    duration = trimmed.size / float(SAMPLE_RATE)
    if trimmed.size == 0 or duration < 0.2:
        return {
            "text": "",
            "duration": 0.0,
            "language": language or "",
            "segments": [],
            "silent": True,
        }

    engine = _ensure_model(model)
    if engine is None:
        raise RuntimeError(_model_error or "本地语音识别模型不可用")

    spoken = language if language is not None else DEFAULT_LANGUAGE
    if spoken in ("", "auto", "none"):
        spoken = None

    segments, info = engine.transcribe(
        trimmed,
        language=spoken,
        beam_size=1,
        best_of=1,
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=False,
        initial_prompt=INITIAL_PROMPT,
    )

    pieces: List[Dict[str, Any]] = []
    for segment in segments:
        text = (getattr(segment, "text", "") or "").strip()
        if not text:
            continue
        pieces.append({
            "start": round(float(getattr(segment, "start", 0.0)), 2),
            "end": round(float(getattr(segment, "end", 0.0)), 2),
            "text": text,
        })

    return {
        "text": "".join(piece["text"] for piece in pieces).strip(),
        "duration": round(duration, 2),
        "language": getattr(info, "language", spoken or ""),
        "segments": pieces,
        "silent": False,
        "elapsed": round(time.time() - started, 2),
        "engine": "faster-whisper",
        "model": model or DEFAULT_MODEL_NAME,
    }
