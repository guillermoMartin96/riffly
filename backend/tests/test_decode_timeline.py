"""Decoder keeps the media timeline (Codex interim review findings 3 and 4)."""

import io

import av
import numpy as np
import pytest
from conftest import tone, upload

from jamrecall.audio import AudioDecodeError, AudioTooLongError, decode_mono


def opus_with_segments(segments: list[tuple[float, np.ndarray]], sr: int = 48000) -> bytes:
    """Opus/WebM whose audio segments start at the given media times (pts gaps allowed)."""
    buf = io.BytesIO()
    with av.open(buf, "w", format="webm") as out:
        stream = out.add_stream("libopus", rate=sr, layout="mono")
        for start, samples in segments:
            pts = int(round(start * sr))
            for i in range(0, samples.size, 960):
                chunk = samples[i : i + 960]
                frame = av.AudioFrame.from_ndarray(
                    chunk.reshape(1, -1), format="flt", layout="mono"
                )
                frame.sample_rate = sr
                frame.pts = pts + i
                for packet in stream.encode(frame):
                    out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def test_gap_between_frames_is_preserved_as_silence(tmp_path):
    p = tmp_path / "gap.webm"
    p.write_bytes(opus_with_segments([(0.0, tone(1.0)), (2.0, tone(1.0, 440))]))
    buf = decode_mono(p, 8000)
    assert abs(buf.duration_seconds - 3.0) < 0.05
    rms = lambda a, b: float(np.sqrt(np.mean(buf.samples[int(a * 8000) : int(b * 8000)] ** 2)))  # noqa: E731
    assert rms(1.2, 1.8) < 0.01  # the gap is silent
    assert rms(2.2, 2.8) > 0.1  # second segment stays at 2 s, not 1 s


def _frames(times: list[float], sr: int = 48000) -> list:
    from fractions import Fraction

    out = []
    for t in times:
        f = av.AudioFrame.from_ndarray(tone(0.4).reshape(1, -1), format="flt", layout="mono")
        f.sample_rate = sr
        f.time_base = Fraction(1, sr)
        f.pts = int(round(t * sr))
        out.append(f)
    return out


class _FakeContainer:
    """Real decoded frames with chosen timestamps (muxers refuse to write out-of-order ones)."""

    def __init__(self, frames):
        from types import SimpleNamespace

        self._frames = frames
        stream = SimpleNamespace(codec_context=SimpleNamespace(sample_rate=48000), rate=48000)
        self.streams = SimpleNamespace(audio=[stream])

    def decode(self, _stream):
        return iter(self._frames)

    def close(self):
        pass


def test_out_of_order_timestamps_are_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(av, "open", lambda _p: _FakeContainer(_frames([0.0, 0.1])))  # overlap
    with pytest.raises(AudioDecodeError, match="out-of-order"):
        decode_mono(tmp_path / "x", 8000)


def test_small_timestamp_jitter_is_tolerated(monkeypatch, tmp_path):
    # 0.4 s frames whose timestamps wobble by +-4 ms are concatenated without gaps or errors.
    monkeypatch.setattr(av, "open", lambda _p: _FakeContainer(_frames([0.0, 0.404, 0.796])))
    buf = decode_mono(tmp_path / "x", 8000)
    assert abs(buf.duration_seconds - 1.2) < 0.01


def test_huge_start_time_rejected_without_allocating(tmp_path):
    p = tmp_path / "late.webm"
    p.write_bytes(opus_with_segments([(36000.0, tone(0.5))]))  # first audio at 10 h
    with pytest.raises(AudioTooLongError):
        decode_mono(p, 22050, max_seconds=600)


def test_upload_refuses_late_start_as_too_long(client, tmp_path):
    r = upload(client, opus_with_segments([(36000.0, tone(0.5))]), "audio/webm")
    assert r.status_code == 413 and r.json()["code"] == "too_long"
    assert client.get("/api/sessions").json() == []
