"""Real Basic Pitch inference (DR-0001). Loads the ONNX model once per module.

Audio is SYNTHETIC (Karplus-Strong pluck), encoded the way browsers record it. These tests check the
integration and clock alignment, not accuracy on real guitar (see docs/research/).
"""

import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from conftest import encoded_bytes, pluck_phrase, upload, wav_bytes
from fastapi.testclient import TestClient

from jamrecall.app import create_app
from jamrecall.audio import decode_mono
from jamrecall.config import Settings
from jamrecall.transcription import registry
from jamrecall.transcription.base import DetectedNote
from jamrecall.transcription.basic_pitch_adapter import BasicPitchAdapter
from jamrecall.transcription.postprocess import monophonic

PITCHES = [45, 52, 57, 60, 64, 67, 72, 76]  # A2 .. E5, guitar range


@pytest.fixture(scope="module")
def adapter():
    return BasicPitchAdapter()


@pytest.fixture(scope="module")
def bp_client(tmp_path_factory, adapter):
    original = registry.REAL_ADAPTERS["basic-pitch"]
    registry.REAL_ADAPTERS["basic-pitch"] = lambda: adapter  # reuse the loaded model
    try:
        settings = Settings(
            data_dir=tmp_path_factory.mktemp("bp"), transcription_engine="basic-pitch"
        )
        yield TestClient(create_app(settings))
    finally:
        registry.REAL_ADAPTERS["basic-pitch"] = original


def test_config_reports_real_provisional_engine(bp_client):
    t = bp_client.get("/api/config").json()["transcription"]
    assert t["engine"] == "basic-pitch"
    assert t["version"].startswith("0.4.0+icassp2022-onnx/on0.7-fr0.4-min58ms")
    assert t["test_only"] is False
    assert t["validated"] is False
    assert t["model_load_seconds"] > 0


CASES = [
    ("audio/wav", 44100, None),
    ("audio/wav", 48000, None),
    ("audio/webm", 48000, ("webm", "libopus", 960)),  # Chrome / Firefox MediaRecorder
    ("audio/ogg", 48000, ("ogg", "libopus", 960)),  # Firefox alternative
    ("audio/mp4", 44100, ("mp4", "aac", 1024)),  # Safari MediaRecorder
]


@pytest.mark.parametrize("mime,sr,enc", CASES, ids=[f"{m}@{r}" for m, r, _ in CASES])
def test_browser_formats_transcribe_with_aligned_onsets(bp_client, mime, sr, enc):
    y, ref = pluck_phrase(PITCHES, sr)
    data = wav_bytes(y, sr) if enc is None else encoded_bytes(y, sr, *enc)
    s = upload(bp_client, data, mime)
    assert s.status_code == 201, s.text
    sid = s.json()["id"]
    assert abs(s.json()["duration_seconds"] - y.size / sr) < 0.06
    assert bp_client.post(f"/api/sessions/{sid}/transcriptions").status_code == 202
    t = bp_client.get(f"/api/sessions/{sid}/transcriptions/latest").json()
    assert t["status"] == "succeeded", t["error"]
    assert t["test_only"] is False and t["engine"] == "basic-pitch"
    assert t["inference_seconds"] > 0 and t["decode_seconds"] > 0
    notes = t["notes"]
    assert [n["midi_pitch"] for n in notes] == PITCHES
    for n, r in zip(notes, ref, strict=True):
        # Source-audio clock: onsets within the benchmark's 50 ms tolerance in every container.
        assert abs(n["start_seconds"] - r["start"]) < 0.05, (mime, n, r)
        assert 0 <= n["confidence"] <= 1
        assert n["duration_seconds"] > 0
        assert n["fingering"]["inferred"] is True


def test_retranscription_keeps_history(bp_client):
    y, _ = pluck_phrase(PITCHES[:3], 22050)
    sid = upload(bp_client, wav_bytes(y, 22050)).json()["id"]
    for _ in range(2):
        bp_client.post(f"/api/sessions/{sid}/transcriptions")
    hist = bp_client.get(f"/api/sessions/{sid}/transcriptions").json()
    assert len(hist) == 2
    assert all(h["status"] == "succeeded" and h["note_count"] == 3 for h in hist)


def test_silence_gives_no_notes(adapter):
    from jamrecall.transcription.base import AudioBuffer

    assert adapter.transcribe(AudioBuffer(np.zeros(22050 * 2, np.float32), 22050)) == []


def test_parity_with_benchmark_pipeline(adapter, tmp_path):
    """The app adapter must reproduce bench/ notes exactly (same model, params, post-process)."""
    bench = Path(__file__).resolve().parents[2] / "bench"
    sys.path.insert(0, str(bench))
    try:
        from jamrecall_bench.methods import bp_analyse, bp_notes
    finally:
        sys.path.remove(str(bench))
    import json

    params = json.loads((bench / "results" / "basic-pitch.json").read_text())["selected_params"]
    y, _ = pluck_phrase(PITCHES, 22050, seed=3)
    path = tmp_path / "p.wav"
    sf.write(path, y, 22050, subtype="FLOAT")
    expected = bp_notes(bp_analyse(path), params)
    got = adapter.transcribe(decode_mono(path, 22050))
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        assert g.midi_pitch == e["midi"]
        assert abs(g.start_seconds - e["start"]) < 1e-4 and abs(g.end_seconds - e["end"]) < 1e-4


def test_monophonic_keeps_most_confident_and_truncates():
    notes = [
        DetectedNote(0.00, 1.00, 60, 0.4),
        DetectedNote(0.02, 0.50, 72, 0.9),  # simultaneous, louder -> wins
        DetectedNote(0.40, 0.80, 62, 0.5),  # truncates the sounding note
        DetectedNote(1.00, 1.20, 64, None),
    ]
    assert monophonic(notes) == [
        DetectedNote(0.02, 0.40, 72, 0.9),
        DetectedNote(0.40, 0.80, 62, 0.5),
        DetectedNote(1.00, 1.20, 64, None),
    ]
