import io
import math
import struct
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np


BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

import asr_api


def wav_bytes(samples, rate=16000, channels=1, width=2):
    """A RIFF/WAVE file holding the given samples."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        if width == 2:
            payload = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        else:
            payload = b"".join(struct.pack("<f", s) for s in samples)
        handle.writeframes(payload)
    return buffer.getvalue()


def tone(seconds=1.0, rate=16000, freq=220.0):
    count = int(seconds * rate)
    return [0.4 * math.sin(2 * math.pi * freq * i / rate) for i in range(count)]


class DecodeTests(unittest.TestCase):
    def test_decodes_16_bit_wav(self):
        samples = tone(0.5)
        decoded = asr_api.decode_audio(wav_bytes(samples))
        self.assertIsNotNone(decoded)
        self.assertEqual(len(decoded), len(samples))
        self.assertAlmostEqual(float(np.max(np.abs(decoded))), 0.4, places=2)

    def test_decodes_stereo_wav_down_to_one_channel(self):
        samples = tone(0.25)
        stereo = []
        for value in samples:
            stereo.extend([value, value])
        decoded = asr_api.decode_audio(wav_bytes(stereo, channels=2))
        self.assertIsNotNone(decoded)
        self.assertEqual(len(decoded), len(samples))

    def test_resamples_a_48k_clip_to_16k(self):
        samples = tone(0.5, rate=48000)
        decoded = asr_api.decode_audio(wav_bytes(samples, rate=48000))
        self.assertIsNotNone(decoded)
        self.assertAlmostEqual(len(decoded) / 16000.0, 0.5, places=2)

    def test_garbage_is_rejected(self):
        self.assertIsNone(asr_api.decode_audio(b"not audio at all"))
        self.assertIsNone(asr_api.decode_audio(b""))


class SilenceTests(unittest.TestCase):
    def test_quiet_clip_is_trimmed_to_nothing(self):
        quiet = [0.0001] * 16000
        trimmed = asr_api._trim_silence(np.asarray(quiet, dtype=np.float32))
        self.assertEqual(trimmed.size, 0)

    def test_speech_in_quiet_is_kept(self):
        samples = [0.0] * 8000 + tone(0.5) + [0.0] * 8000
        trimmed = asr_api._trim_silence(np.asarray(samples, dtype=np.float32))
        self.assertGreater(trimmed.size, 8000)


class FakeSegment:
    def __init__(self, text):
        self.text = text
        self.start = 0.0
        self.end = 1.0


class FakeInfo:
    language = "zh"


class FakeModel:
    def __init__(self, text="我想做一个可爱的桌面摆件"):
        self.text = text
        self.calls = []

    def transcribe(self, samples, **kwargs):
        self.calls.append((samples, kwargs))
        return iter([FakeSegment(self.text)]), FakeInfo()


class TranscribeTests(unittest.TestCase):
    def test_transcribes_a_clip_with_the_local_model(self):
        model = FakeModel()
        with patch.object(asr_api, "_ensure_model", return_value=model):
            result = asr_api.transcribe(wav_bytes(tone(1.0)))
        self.assertEqual(result["text"], "我想做一个可爱的桌面摆件")
        self.assertEqual(result["engine"], "faster-whisper")
        self.assertFalse(result["silent"])
        self.assertEqual(model.calls[0][1]["language"], "zh")

    def test_silence_is_reported_without_calling_the_model(self):
        model = FakeModel()
        with patch.object(asr_api, "_ensure_model", return_value=model):
            result = asr_api.transcribe(wav_bytes([0.0] * 1600))
        self.assertTrue(result["silent"])
        self.assertEqual(result["text"], "")
        self.assertEqual(model.calls, [])

    def test_a_missing_model_is_reported(self):
        with patch.object(asr_api, "_ensure_model", return_value=None):
            with patch.object(asr_api, "_model_error", "语音识别模型未安装"):
                with self.assertRaises(RuntimeError):
                    asr_api.transcribe(wav_bytes(tone(1.0)))

    def test_unreadable_audio_is_reported(self):
        with self.assertRaises(RuntimeError):
            asr_api.transcribe(b"definitely not audio")


class StatusTests(unittest.TestCase):
    def test_status_describes_the_engine(self):
        status = asr_api.status()
        self.assertEqual(status["engine"], "faster-whisper")
        self.assertEqual(status["sample_rate"], 16000)
        self.assertIn("model", status)


if __name__ == "__main__":
    unittest.main()
