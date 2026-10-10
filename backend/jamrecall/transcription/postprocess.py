"""Provider-independent post-processing of normalized note events."""

from __future__ import annotations

from jamrecall.transcription.base import DetectedNote

SIMULTANEOUS_S = 0.05


def monophonic(notes: list[DetectedNote]) -> list[DetectedNote]:
    """Keep one note at a time.

    Among notes starting within 50 ms of each other keep the most confident; a later onset truncates
    the sounding note. Notes without confidence count as 0. Matches the benchmark's mono variant
    (bench/jamrecall_bench/methods.py::monophonic).
    """

    def conf(n: DetectedNote) -> float:
        return n.confidence if n.confidence is not None else 0.0

    ordered = sorted(notes, key=lambda n: (n.start_seconds, -conf(n)))
    out: list[DetectedNote] = []
    for n in ordered:
        if out and n.start_seconds - out[-1].start_seconds < SIMULTANEOUS_S:
            if conf(n) > conf(out[-1]):
                out[-1] = n
            continue
        if out and out[-1].end_seconds > n.start_seconds:
            prev = out[-1]
            out[-1] = DetectedNote(
                prev.start_seconds, n.start_seconds, prev.midi_pitch, prev.confidence
            )
        out.append(n)
    return [n for n in out if n.end_seconds > n.start_seconds]
