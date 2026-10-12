"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Browser MediaRecorder container types we accept. Parameters (";codecs=...") are stripped first.
ACCEPTED_MIME_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/wav", "audio/x-wav")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    # Name of the transcription engine to run, or None when no engine is configured.
    # from_env() defaults to "basic-pitch" (DR-0001); JAMRECALL_TRANSCRIPTION_ENGINE=none
    # disables transcription.
    transcription_engine: str | None = None
    # Test-only adapters (fixture, failing) are refused unless this is set.
    allow_test_adapters: bool = False
    max_upload_bytes: int = 50 * 1024 * 1024
    max_duration_seconds: float = 600.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jamrecall.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @classmethod
    def from_env(cls) -> Settings:
        default_dir = Path(__file__).resolve().parents[2] / "var"
        return cls(
            data_dir=Path(os.environ.get("JAMRECALL_DATA_DIR", default_dir)),
            transcription_engine=os.environ.get("JAMRECALL_TRANSCRIPTION_ENGINE") or "basic-pitch",
            allow_test_adapters=_truthy(os.environ.get("JAMRECALL_ALLOW_TEST_ADAPTERS")),
        )
