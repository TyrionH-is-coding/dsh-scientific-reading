"""MinerU provider 协议和一次性选择策略。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .mineru_api import API_CONTRACT_VERSION, DEFAULT_MODEL_VERSION, MineruApiClient
from .secret_store import resolve_mineru_token


class MineruProviderError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MineruProbe:
    provider_id: str
    version: str
    status: str


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider_id: str
    version: str
    raw_root: Path
    model_version: str | None = None
    batch_id: str | None = None
    result_zip_sha256: str | None = None


class MineruProvider(Protocol):
    provider_id: str
    version: str

    def probe(self) -> MineruProbe: ...
    def parse(
        self,
        pdf: Path,
        staging: Path,
        method: str,
        heartbeat: Callable[[], None],
    ) -> ProviderResult: ...


def choose_provider(
    strategy: str, *, local: MineruProvider, api: MineruProvider
) -> MineruProvider:
    if strategy not in {"auto", "local", "api"}:
        raise MineruProviderError("mineru_strategy_invalid")
    local_probe = local.probe()
    api_probe = api.probe()
    if strategy == "local":
        if local_probe.status != "ready":
            raise MineruProviderError("mineru_local_unavailable")
        return local
    if strategy == "api":
        if api_probe.status != "ready":
            raise MineruProviderError("mineru_api_unavailable")
        return api
    if local_probe.status == "ready":
        return local
    if api_probe.status == "ready":
        return api
    raise MineruProviderError("mineru_provider_unavailable")


class ApiMineruProvider:
    provider_id = API_CONTRACT_VERSION
    version = DEFAULT_MODEL_VERSION

    def __init__(
        self,
        data_root: Path,
        *,
        data_id: str,
        checkpoint_path: Path,
        client_factory=None,
    ) -> None:
        self.data_root = Path(data_root)
        self.data_id = data_id
        self.checkpoint_path = checkpoint_path
        self.client_factory = client_factory or (lambda token: MineruApiClient(token))

    def probe(self) -> MineruProbe:
        token, _source = resolve_mineru_token(self.data_root)
        return MineruProbe(
            self.provider_id,
            self.version,
            "ready" if token else "not_configured",
        )

    def parse(self, pdf: Path, staging: Path, method: str, heartbeat) -> ProviderResult:
        token, _source = resolve_mineru_token(self.data_root)
        if token is None:
            raise MineruProviderError("mineru_api_token_required")
        result = self.client_factory(token).parse(
            pdf,
            staging,
            data_id=self.data_id,
            checkpoint_path=self.checkpoint_path,
            heartbeat=heartbeat,
        )
        return ProviderResult(
            provider_id=self.provider_id,
            version=result.model_version,
            raw_root=Path(staging).resolve(),
            model_version=result.model_version,
            batch_id=result.batch_id,
            result_zip_sha256=result.result_zip_sha256,
        )
