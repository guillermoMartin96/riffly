"""Engine selection.

No production engine is registered until the tech lead approves one (DR-0001).
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

REAL_ADAPTERS: dict[str, Callable[[], TranscriptionAdapter]] = {}


class EngineConfigError(Exception):
    pass


def build_adapter(settings: Settings) -> TranscriptionAdapter | None:
    name = settings.transcription_engine
    if name is None:
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
