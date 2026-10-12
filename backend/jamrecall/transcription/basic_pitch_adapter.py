"""Basic Pitch 0.4.0 (Spotify, Apache-2.0) via its bundled ONNX model. Approved in DR-0001.

Inference repeats `basic_pitch.inference.run_inference` on an in-memory buffer (the app's own
PyAV decode at 22,050 Hz) instead of a file path, using the library's public windowing and
unwrapping helpers. Note extraction parameters were selected on the GuitarSet dev split
(bench/results/basic-pitch.json).
Validation status is provisional until the real-recording gate passes (DR-0001 decision 2).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jamrecall.transcription.base import AudioBuffer, DetectedNote, TranscriptionError
from jamrecall.transcription.postprocess import monophonic

log = logging.getLogger(__name__)

N_OVERLAPPING_FRAMES = 30
PARAMS_FILE = Path(__file__).with_name("basic_pitch_params.json")


@dataclass(frozen=True)
class BasicPitchParams:
    onset_thresh: float = 0.7
    frame_thresh: float = 0.4
    min_note_ms: float = 58.0
    min_freq_hz: float = 75.0  # below low E (82.4 Hz)
    max_freq_hz: float = 1400.0  # above the 20th fret on high E (1046.5 Hz)
    mono: bool = True

    @classmethod
    def app_default(cls) -> BasicPitchParams:
        """The parameters the app runs, from basic_pitch_params.json (shared with bench/)."""
        data = json.loads(PARAMS_FILE.read_text())
        return cls(**{k: v for k, v in data.items() if not k.startswith("_")})

    def tag(self) -> str:
        return (
            f"on{self.onset_thresh}-fr{self.frame_thresh}-min{self.min_note_ms:g}ms-"
            f"{self.min_freq_hz:g}-{self.max_freq_hz:g}Hz{'-mono' if self.mono else ''}"
        )


class BasicPitchAdapter:
    engine = "basic-pitch"
    test_only = False
    validated = False  # provisional until real-recording validation passes (DR-0001)
    sample_rate = 22050

    def __init__(self, params: BasicPitchParams | None = None):
        try:
            from basic_pitch import ICASSP_2022_MODEL_PATH
            from basic_pitch.constants import AUDIO_SAMPLE_RATE
            from basic_pitch.inference import Model
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "basic-pitch is not installed; run backend/install.sh (see DR-0001)"
            ) from exc
        assert AUDIO_SAMPLE_RATE == self.sample_rate
        self.params = params or BasicPitchParams.app_default()
        self.version = f"0.4.0+icassp2022-onnx/{self.params.tag()}"
        model_path = Path(ICASSP_2022_MODEL_PATH).parent / "nmp.onnx"
        t0 = time.perf_counter()
        self._model = Model(model_path)
        self.load_seconds = time.perf_counter() - t0
        log.info("loaded Basic Pitch ONNX model in %.2fs", self.load_seconds)

    def model_output(self, samples: np.ndarray) -> dict[str, np.ndarray]:
        from basic_pitch.constants import AUDIO_N_SAMPLES, FFT_HOP
        from basic_pitch.inference import unwrap_output, window_audio_file

        overlap_len = N_OVERLAPPING_FRAMES * FFT_HOP
        hop_size = AUDIO_N_SAMPLES - overlap_len
        x = np.concatenate([np.zeros(overlap_len // 2, np.float32), samples.astype(np.float32)])
        out: dict[str, list] = {"note": [], "onset": [], "contour": []}
        for window, _ in window_audio_file(x, hop_size):
            for k, v in self._model.predict(np.expand_dims(window, axis=0)).items():
                out[k].append(v)
        return {
            k: unwrap_output(np.concatenate(v), samples.shape[0], N_OVERLAPPING_FRAMES)
            for k, v in out.items()
        }

    def transcribe(self, audio: AudioBuffer) -> list[DetectedNote]:
        from basic_pitch.constants import FFT_HOP
        from basic_pitch.note_creation import model_output_to_notes

        if audio.sample_rate != self.sample_rate:
            raise TranscriptionError(
                f"expected {self.sample_rate} Hz audio, got {audio.sample_rate}"
            )
        if audio.samples.size == 0:
            return []
        p = self.params
        try:
            output = self.model_output(audio.samples)
            _, events = model_output_to_notes(
                output,
                onset_thresh=p.onset_thresh,
                frame_thresh=p.frame_thresh,
                min_note_len=int(np.round(p.min_note_ms / 1000 * (self.sample_rate / FFT_HOP))),
                min_freq=p.min_freq_hz,
                max_freq=p.max_freq_hz,
                include_pitch_bends=False,
                melodia_trick=True,
            )
        except Exception as exc:
            raise TranscriptionError(f"Basic Pitch inference failed: {exc}") from exc
        # Basic Pitch's per-note amplitude (mean note posterior, 0-1) is reported as confidence.
        notes = [DetectedNote(float(s), float(e), int(m), float(a)) for s, e, m, a, _ in events]
        return monophonic(notes) if p.mono else notes
