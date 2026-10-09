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


# Inter-frame timestamp jitter tolerated without adjustment (container timestamp rounding).
TIMESTAMP_TOLERANCE_S = 0.01
RESAMPLE_BLOCK = 1 << 16


class AudioDecodeError(Exception):
    pass


class AudioTooLongError(AudioDecodeError):
    pass


def decode_mono(
    path: Path, sample_rate: int = ANALYSIS_SAMPLE_RATE, max_seconds: float | None = None
) -> AudioBuffer:
    """Decode to mono float32 at `sample_rate`, with each frame placed at its presentation time.

    Frames are placed on a native-rate timeline that starts at media time 0. A gap between frames
    (> 10 ms) becomes silence; overlapping or backwards timestamps are rejected. `max_seconds` is
    enforced while decoding, so oversized or malicious inputs are refused before large allocations.
    """
    try:
        container = av.open(str(path))
    except (av.error.FFmpegError, OSError) as exc:
        raise AudioDecodeError(f"cannot open audio: {exc}") from exc
    try:
        streams = container.streams.audio
        if not streams:
            raise AudioDecodeError("file contains no audio stream")
        stream = streams[0]
        native = int(stream.codec_context.sample_rate or stream.rate or sample_rate)
        tol = int(TIMESTAMP_TOLERANCE_S * native)
        limit = None if max_seconds is None else int(max_seconds * native) + tol
        to_mono = av.AudioResampler(format="flt", layout="mono", rate=native)
        parts: list[np.ndarray] = []
        cursor = 0  # samples placed so far on the native timeline

        def place(chunk: np.ndarray, at_time: float | None) -> None:
            nonlocal cursor
            if at_time is not None:
                gap = int(round(max(0.0, at_time) * native)) - cursor
                if gap > tol:
                    if limit is not None and cursor + gap > limit:
                        raise AudioTooLongError("recording exceeds the maximum duration")
                    parts.append(np.zeros(gap, np.float32))
                    cursor += gap
                elif gap < -tol:
                    raise AudioDecodeError(
                        f"overlapping or out-of-order audio timestamps at {at_time:.3f} s"
                    )
            if limit is not None and cursor + chunk.size > limit:
                raise AudioTooLongError("recording exceeds the maximum duration")
            parts.append(chunk)
            cursor += chunk.size

        try:
            for frame in container.decode(stream):
                t = None if frame.time is None else float(frame.time)
                for out in to_mono.resample(frame):
                    place(out.to_ndarray().reshape(-1).astype(np.float32), t)
                    t = None  # only the first output chunk carries the frame's timestamp
            for out in to_mono.resample(None):
                place(out.to_ndarray().reshape(-1).astype(np.float32), None)
        except av.error.FFmpegError as exc:
            raise AudioDecodeError(f"cannot decode audio: {exc}") from exc
    finally:
        container.close()

    if not parts or cursor == 0:
        raise AudioDecodeError("recording contains no audio samples")
    samples = np.concatenate(parts)
    if native != sample_rate:
        samples = _resample(samples, native, sample_rate)
    return AudioBuffer(samples=samples, sample_rate=sample_rate)


def _resample(samples: np.ndarray, src: int, dst: int) -> np.ndarray:
    resampler = av.AudioResampler(format="flt", layout="mono", rate=dst)
    out: list[np.ndarray] = []
    for i in range(0, samples.size, RESAMPLE_BLOCK):
        block = samples[i : i + RESAMPLE_BLOCK]
        frame = av.AudioFrame.from_ndarray(block.reshape(1, -1), format="flt", layout="mono")
        frame.sample_rate = src
        frame.pts = i
        for o in resampler.resample(frame):
            out.append(o.to_ndarray().reshape(-1))
    for o in resampler.resample(None):
        out.append(o.to_ndarray().reshape(-1))
    return np.concatenate(out).astype(np.float32)


def peaks(buffer: AudioBuffer, buckets: int) -> list[float]:
    """Max absolute amplitude per equal-width time bucket (for waveform display)."""
    buckets = max(1, min(buckets, 20000))
    x = np.abs(buffer.samples)
    edges = np.linspace(0, x.size, buckets + 1).astype(int)
    out = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        out.append(float(x[a:b].max()) if b > a else 0.0)
    return [round(v, 4) for v in out]
