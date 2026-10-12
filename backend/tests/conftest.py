from __future__ import annotations

import io
import wave
from pathlib import Path

import av
import numpy as np
import pytest
from fastapi.testclient import TestClient

from jamrecall.app import create_app
from jamrecall.config import Settings


def tone(seconds: float, freq: float = 220.0, sr: int = 48000) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (0.4 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def wav_bytes(samples: np.ndarray, sr: int = 48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def pluck_phrase(
    pitches: list[int],
    sr: int,
    start: float = 0.3,
    step: float = 0.45,
    dur: float = 0.4,
    seed: int = 0,
) -> tuple[np.ndarray, list[dict]]:
    """Karplus-Strong plucked-string phrase (synthetic, not guitar) with exact reference notes."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int((start + step * len(pitches) + 0.5) * sr))
    ref = []
    for i, midi in enumerate(pitches):
        period = int(round(sr / (440 * 2 ** ((midi - 69) / 12))))
        buf = rng.uniform(-1, 1, period)
        n = int(dur * sr)
        out = np.empty(n)
        for k in range(n):
            j = k % period
            out[k] = buf[j]
            buf[j] = 0.996 * 0.5 * (buf[j] + buf[(j + 1) % period])
        fade = int(0.02 * sr)
        out[-fade:] *= np.linspace(1, 0, fade)
        a = int((start + i * step) * sr)
        y[a : a + n] += out
        ref.append({"start": start + i * step, "end": start + i * step + dur, "midi": midi})
    return (0.5 * y / np.abs(y).max()).astype(np.float32), ref


def webm_opus_bytes(samples: np.ndarray, sr: int = 48000) -> bytes:
    """Encode like Chrome's MediaRecorder default (Opus in WebM)."""
    return encoded_bytes(samples, sr, "webm", "libopus", 960)


def encoded_bytes(samples: np.ndarray, sr: int, fmt: str, codec: str, frame_size: int) -> bytes:
    """Encode mono float samples with PyAV: webm/libopus, ogg/libopus or mp4/aac."""
    sample_fmt = "fltp" if codec == "aac" else "flt"
    buf = io.BytesIO()
    with av.open(buf, "w", format=fmt) as out:
        stream = out.add_stream(codec, rate=sr, layout="mono")
        pts = 0
        for i in range(0, samples.size, frame_size):
            chunk = samples[i : i + frame_size]
            frame = av.AudioFrame.from_ndarray(
                chunk.reshape(1, -1), format=sample_fmt, layout="mono"
            )
            frame.sample_rate = sr
            frame.pts = pts
            pts += chunk.size
            for packet in stream.encode(frame):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


@pytest.fixture
def make_client(tmp_path: Path):
    def _make(**overrides) -> TestClient:
        settings = Settings(data_dir=tmp_path / "data", **overrides)
        return TestClient(create_app(settings))

    return _make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def fixture_client(make_client) -> TestClient:
    return make_client(transcription_engine="fixture", allow_test_adapters=True)


def upload(client: TestClient, data: bytes, mime: str = "audio/wav"):
    return client.post(
        "/api/sessions",
        files={"audio": ("rec", data, mime)},
        data={"client_mime": mime},
    )
