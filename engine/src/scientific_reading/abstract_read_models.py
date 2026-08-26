from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ABSTRACT_TRANSLATION_CONTRACT_VERSION = "abstract-translation-v1"

@dataclass(frozen=True, slots=True)
class AbstractTranslation:
    source_sha256: str
    paragraphs: list[dict[str, Any]]
    contract_version: str = ABSTRACT_TRANSLATION_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {"contract_version": self.contract_version, "source_sha256": self.source_sha256, "paragraphs": self.paragraphs}
