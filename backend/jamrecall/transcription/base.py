"""Transcription adapter contract and the normalized note-event schema.

Every engine (real or test-only) implements `TranscriptionAdapter`. Whatever an engine returns is
passed through `normalize_notes` before it is persisted, so downstream code only ever sees
events with 0 <= start < end <= duration, integer MIDI pitch 0-127, and confidence in [0, 1] or
None.
Times are seconds on the source-audio clock; intervals are half-open [start, end).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class AudioBuffer:
    samples: np.ndarray  # mono float32
    sample_rate: int

    @property
    def duration_seconds(self) -> float:
        return self.samples.size / self.sample_rate


@dataclass(frozen=True)
class DetectedNote:
    start_seconds: float
    end_seconds: float
    midi_pitch: int
    confidence: float | None = None


class TranscriptionError(Exception):
    """Engine failed; `str(exc)` is persisted as the transcription's failure reason."""


@runtime_checkable
class TranscriptionAdapter(Protocol):
    engine: str
    version: str
    # True for adapters whose output does not come from the audio content (fixtures).
    test_only: bool
    # Sample rate the adapter wants its AudioBuffer decoded at.
    sample_rate: int

    def transcribe(self, audio: AudioBuffer) -> list[DetectedNote]: ...


def normalize_notes(notes: list[DetectedNote], duration_seconds: float) -> list[DetectedNote]:
    """Clip to [0, duration), drop degenerate/invalid events, and sort by onset then pitch."""
    out: list[DetectedNote] = []
    for n in notes:
        if not all(math.isfinite(v) for v in (n.start_seconds, n.end_seconds)):
            continue
        start = max(0.0, float(n.start_seconds))
        end = min(float(duration_seconds), float(n.end_seconds))
        if end <= start:
            continue
        midi = int(round(n.midi_pitch))
        if not 0 <= midi <= 127:
            continue
        conf = n.confidence
        if conf is not None:
            conf = float(conf)
            conf = None if not math.isfinite(conf) else min(1.0, max(0.0, conf))
        out.append(DetectedNote(round(start, 6), round(end, 6), midi, conf))
    out.sort(key=lambda n: (n.start_seconds, n.midi_pitch))
    return out
