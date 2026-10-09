"""Shared paths and the common note-event format used by every corpus and method.

Note event: {"start": seconds, "end": seconds, "midi": int} on the clip's own clock, [start, end).
"""

from __future__ import annotations

import json
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
CACHE = BENCH / ".cache"
CORPUS = CACHE / "corpus"
PRED = CACHE / "predictions"
RESULTS = BENCH / "results"


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True))


def read_json(path: Path):
    return json.loads(path.read_text())


def load_manifest(corpus: str) -> dict:
    return read_json(CORPUS / corpus / "manifest.json")
