from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PaperMetadata:
    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    pmid: str | None = None
    year: int | None = None
    journal: str | None = None
    library_key: str | None = None
    abstract_en: str | None = None
    abstract_zh: str | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = {
            "title": self.title,
            "authors": self.authors,
            "doi": self.doi,
            "pmid": self.pmid,
            "year": self.year,
            "journal": self.journal,
            "library_key": self.library_key,
            "abstract_en": self.abstract_en,
            "abstract_zh": self.abstract_zh,
            "source_url": self.source_url,
        }
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PaperMetadata:
        if not isinstance(value, Mapping):
            raise ValueError("metadata_mapping_required")
        string_fields = (
            "title",
            "doi",
            "pmid",
            "journal",
            "library_key",
            "abstract_en",
            "abstract_zh",
            "source_url",
        )
        if any(
            value.get(name) is not None
            and not isinstance(value.get(name), str)
            for name in string_fields
        ):
            raise ValueError("metadata_string_field_invalid")
        authors = value.get("authors")
        if authors is not None and (
            not isinstance(authors, list)
            or any(not isinstance(author, str) for author in authors)
        ):
            raise ValueError("metadata_authors_invalid")
        year = value.get("year")
        if year is not None and (
            not isinstance(year, int) or isinstance(year, bool)
        ):
            raise ValueError("metadata_year_invalid")
        return cls(
            title=value.get("title") or "",
            authors=list(authors or []),
            doi=value.get("doi"),
            pmid=value.get("pmid"),
            year=value.get("year"),
            journal=value.get("journal"),
            library_key=value.get("library_key"),
            abstract_en=value.get("abstract_en"),
            abstract_zh=value.get("abstract_zh"),
            source_url=value.get("source_url"),
        )


@dataclass(slots=True)
class StageRecord:
    status: str = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    input_hash: str | None = None
    tool_version: str | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StageRecord:
        return cls(**value)


@dataclass(slots=True)
class JobState:
    paper_id: str
    status: str = "received"
    stages: dict[str, StageRecord] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> JobState:
        stages = {
            name: StageRecord.from_dict(stage)
            for name, stage in value.get("stages", {}).items()
        }
        return cls(
            paper_id=value["paper_id"],
            status=value.get("status", "received"),
            stages=stages,
            error=value.get("error"),
        )


@dataclass(slots=True)
class AssetRecord:
    asset_id: str
    kind: str
    page: int
    relative_path: str = ""
    label: str | None = None
    caption: str | None = None
    source_index: int | None = None
    is_body: bool | None = None
    is_body_source: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    bbox_reliable: bool = False
    source_sha256: str | None = None
    structured_reliable: bool = False
    structured_path: str | None = None
    structured_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> AssetRecord:
        known = cls.__dataclass_fields__
        filtered = {
            key: item for key, item in value.items() if key in known
        }
        if isinstance(filtered.get("bbox"), list):
            filtered["bbox"] = tuple(filtered["bbox"])
        return cls(**filtered)
