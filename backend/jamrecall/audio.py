"""Decode stored recordings into mono PCM on the source-audio clock.

The original upload is never modified. Decoding uses PyAV (FFmpeg libraries bundled in its wheel).
Sample index 0 of the returned buffer corresponds to media time 0, the same origin an HTML <audio>
element uses, so note and riff timestamps line up with browser playback.
"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np

from jamrecall.transcription.base import AudioBuffer

ANALYSIS_SAMPLE_RATE = 22050


class AudioDecodeError(Exception):
    pass


def decode_mono(path: Path, sample_rate: int = ANALYSIS_SAMPLE_RATE) -> AudioBuffer:
    try:
        container = av.open(str(path))
    except (av.error.FFmpegError, OSError) as exc:
        raise AudioDecodeError(f"cannot open audio: {exc}") from exc
    try:
        streams = container.streams.audio
        if not streams:
            raise AudioDecodeError("file contains no audio stream")
        stream = streams[0]
        resampler = av.AudioResampler(format="flt", layout="mono", rate=sample_rate)
        chunks: list[np.ndarray] = []
        first_time: float | None = None
        try:
            for frame in container.decode(stream):
                if first_time is None and frame.time is not None:
                    first_time = max(0.0, float(frame.time))
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray().reshape(-1))
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray().reshape(-1))
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"cannot decode audio: {exc}") from exc
    finally:
        container.close()

    samples = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    if samples.size == 0:
        raise AudioDecodeError("recording contains no audio samples")
    # If the first decoded frame starts after media time 0, pad so index 0 == media time 0.
    lead = int(round((first_time or 0.0) * sample_rate))
    if lead > 0:
        samples = np.concatenate([np.zeros(lead, np.float32), samples])
    return AudioBuffer(samples=samples, sample_rate=sample_rate)


def peaks(buffer: AudioBuffer, buckets: int) -> list[float]:
    """Max absolute amplitude per equal-width time bucket (for waveform display)."""
    buckets = max(1, min(buckets, 20000))
    x = np.abs(buffer.samples)
    edges = np.linspace(0, x.size, buckets + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        out.append(float(x[a:b].max()) if b > a else 0.0)
    return [round(v, 4) for v in out]
