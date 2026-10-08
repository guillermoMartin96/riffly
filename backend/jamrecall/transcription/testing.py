"""TEST-ONLY adapters. Their output is NOT derived from the audio content.

They exist so UI and integration tests can exercise the transcription workflow and its error paths
before a real engine is approved. They are refused unless JAMRECALL_ALLOW_TEST_ADAPTERS is set, and
every transcription they produce is persisted with test_only=1 and shown with a fixture banner.
"""

from __future__ import annotations

from jamrecall.transcription.base import AudioBuffer, DetectedNote, TranscriptionError

# A deliberately artificial chromatic run (C3 upward), repeated over the recording length, so
# fixture output can never be mistaken for a plausible transcription of a real phrase.
_FIXTURE_PITCHES = [48, 49, 50, 51, 52, 53, 54, 55]


class FixtureAdapter:
    engine = "test-fixture"
    version = "1"
    test_only = True
    sample_rate = 8000

    def transcribe(self, audio: AudioBuffer) -> list[DetectedNote]:
        notes = []
        t, i = 0.25, 0
        while t + 0.4 <= audio.duration_seconds:
            pitch = _FIXTURE_PITCHES[i % len(_FIXTURE_PITCHES)]
            notes.append(DetectedNote(t, t + 0.4, pitch, None))
            t += 0.5
            i += 1
        return notes


class FailingAdapter:
    engine = "test-failing"
    version = "1"
    test_only = True
    sample_rate = 8000

    def transcribe(self, audio: AudioBuffer) -> list[DetectedNote]:
        raise TranscriptionError("test-failing adapter always fails (simulated engine error)")
