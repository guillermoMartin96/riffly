"""Engine selection.

Production engine: Basic Pitch (DR-0001, provisionally approved 2026-10-09). pYIN stays in
bench/ only (DR-0001 decision 3). Engines are constructed once per app process (model loaded
at startup).
"""

from __future__ import annotations

from collections.abc import Callable

from jamrecall.config import Settings
from jamrecall.transcription.base import TranscriptionAdapter
from jamrecall.transcription.testing import FailingAdapter, FixtureAdapter

TEST_ADAPTERS: dict[str, Callable[[], TranscriptionAdapter]] = {
    "fixture": FixtureAdapter,
    "failing": FailingAdapter,
}


def _basic_pitch() -> TranscriptionAdapter:
    from jamrecall.transcription.basic_pitch_adapter import BasicPitchAdapter

    return BasicPitchAdapter()


REAL_ADAPTERS: dict[str, Callable[[], TranscriptionAdapter]] = {"basic-pitch": _basic_pitch}


class EngineConfigError(Exception):
    pass


def build_adapter(settings: Settings) -> TranscriptionAdapter | None:
    name = settings.transcription_engine
    if name is None or name == "none":
        return None
    if name in REAL_ADAPTERS:
        return REAL_ADAPTERS[name]()
    if name in TEST_ADAPTERS:
        if not settings.allow_test_adapters:
            raise EngineConfigError(
                f"engine '{name}' is test-only; set JAMRECALL_ALLOW_TEST_ADAPTERS=1 to use it"
            )
        return TEST_ADAPTERS[name]()
    raise EngineConfigError(f"unknown transcription engine '{name}'")
