from __future__ import annotations

from pathlib import Path

import pytest

from scientific_reading.mineru_provider import (
    MineruProbe,
    MineruProviderError,
    choose_provider,
)


class Provider:
    def __init__(self, provider_id: str, status: str) -> None:
        self.provider_id = provider_id
        self.version = "1.0"
        self.status = status
        self.parse_calls = 0

    def probe(self) -> MineruProbe:
        return MineruProbe(self.provider_id, self.version, self.status)

    def parse(self, pdf: Path, staging: Path, method: str, heartbeat):
        self.parse_calls += 1
        raise RuntimeError("parse_failed")


def test_auto_prefers_ready_local_then_api() -> None:
    local = Provider("mineru-local-v1", "ready")
    api = Provider("mineru-api-v4", "ready")
    assert choose_provider("auto", local=local, api=api) is local
    assert choose_provider("auto", local=Provider("mineru-local-v1", "unavailable"), api=api) is api


def test_explicit_provider_never_silently_falls_back() -> None:
    local = Provider("mineru-local-v1", "unavailable")
    api = Provider("mineru-api-v4", "ready")
    with pytest.raises(MineruProviderError, match="mineru_local_unavailable"):
        choose_provider("local", local=local, api=api)
    assert api.parse_calls == 0
    with pytest.raises(MineruProviderError, match="mineru_api_unavailable"):
        choose_provider("api", local=Provider("mineru-local-v1", "ready"), api=Provider("mineru-api-v4", "unavailable"))


def test_auto_fails_when_no_provider_is_ready() -> None:
    with pytest.raises(MineruProviderError, match="mineru_provider_unavailable"):
        choose_provider(
            "auto",
            local=Provider("mineru-local-v1", "unavailable"),
            api=Provider("mineru-api-v4", "not_configured"),
        )
