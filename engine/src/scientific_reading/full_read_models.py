from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


FULL_TRANSLATION_CONTRACT_VERSION = "full-translation-v3"
FULL_REVIEW_CONTRACT_VERSION = "full-review-v2"
HIGHLIGHT_KINDS = frozenset({"result", "method", "none"})
GUIDE_LIMITS = {
    "research_question": 1,
    "key_methods": 2,
    "core_results": 3,
    "limitations": 2,
}
_MINERU_BLOCK_ID = re.compile(r"p[0-9]{4}-(?:m|c)[0-9]{4}")


def _exact_keys(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise ValueError("unexpected_keys")


@dataclass(frozen=True, slots=True)
class Translation:
    block_id: str
    source_text: str
    translation_zh: str
    highlight: str

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        expected_source_text: str,
        reference: bool,
    ) -> Translation:
        if not isinstance(value, dict):
            raise ValueError("translation_row_invalid")
        _exact_keys(
            value,
            {"block_id", "source_text", "translation_zh", "highlight"},
        )
        block_id = value["block_id"]
        if (
            not isinstance(block_id, str)
            or _MINERU_BLOCK_ID.fullmatch(block_id) is None
        ):
            raise ValueError("translation_block_id_invalid")
        source_text = value["source_text"]
        if source_text != expected_source_text:
            raise ValueError("translation_source_text_mismatch")
        translation_zh = value["translation_zh"]
        if not isinstance(translation_zh, str):
            raise ValueError("translation_zh_required")
        if not reference and not translation_zh.strip():
            raise ValueError("translation_zh_required")
        highlight = value["highlight"]
        if highlight not in HIGHLIGHT_KINDS:
            raise ValueError("translation_highlight_invalid")
        if reference and translation_zh.strip():
            raise ValueError("reference_translation_forbidden")
        if reference and highlight != "none":
            raise ValueError("reference_highlight_forbidden")
        return cls(
            block_id=block_id,
            source_text=source_text,
            translation_zh=translation_zh.strip(),
            highlight=highlight,
        )

    @property
    def chinese(self) -> str:
        return self.translation_zh

    @property
    def note(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class TranslationBatchSubmission:
    contract_version: str
    batch_id: str
    source_sha256: str
    translations: tuple[Translation, ...]

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        expected_blocks: Iterable[dict[str, Any]],
        expected_batch_id: str,
        expected_source_sha256: str,
    ) -> TranslationBatchSubmission:
        if not isinstance(value, dict):
            raise ValueError("translation_submission_invalid")
        _exact_keys(
            value,
            {
                "contract_version",
                "batch_id",
                "source_sha256",
                "translations",
            },
        )
        if value["contract_version"] != FULL_TRANSLATION_CONTRACT_VERSION:
            raise ValueError("translation_contract_invalid")
        if value["batch_id"] != expected_batch_id:
            raise ValueError("translation_batch_mismatch")
        if value["source_sha256"] != expected_source_sha256:
            raise ValueError("translation_source_sha_mismatch")
        rows = value["translations"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("translation_rows_required")
        source_rows = tuple(expected_blocks)
        if len(rows) != len(source_rows):
            raise ValueError("translation_block_order_mismatch")
        if any(
            not isinstance(row, dict)
            or not isinstance(row.get("block_id"), str)
            or _MINERU_BLOCK_ID.fullmatch(row["block_id"]) is None
            for row in rows
        ):
            raise ValueError("translation_block_id_invalid")
        if tuple(row.get("block_id") for row in rows) != tuple(
            row["block_id"] for row in source_rows
        ):
            raise ValueError("translation_block_order_mismatch")
        translations = tuple(
            Translation.from_dict(
                row,
                expected_source_text=source["english"],
                reference=source.get("source_type") == "reference",
            )
            for row, source in zip(rows, source_rows, strict=True)
        )
        return cls(
            contract_version=FULL_TRANSLATION_CONTRACT_VERSION,
            batch_id=expected_batch_id,
            source_sha256=expected_source_sha256,
            translations=translations,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "batch_id": self.batch_id,
            "source_sha256": self.source_sha256,
            "translations": [
                asdict(translation)
                for translation in self.translations
            ],
        }


@dataclass(frozen=True, slots=True)
class GuideEntry:
    text: str
    source_block_ids: tuple[str, ...]

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        available_block_ids: set[str],
    ) -> GuideEntry:
        if not isinstance(value, dict):
            raise ValueError("guide_entry_invalid")
        _exact_keys(value, {"text", "source_block_ids"})
        text = value["text"]
        if not isinstance(text, str) or not text.strip():
            raise ValueError("guide_text_required")
        text = text.strip()
        if len(text) > 240:
            raise ValueError("guide_text_too_long")
        block_ids = value["source_block_ids"]
        if (
            not isinstance(block_ids, list)
            or not 1 <= len(block_ids) <= 3
            or any(not isinstance(item, str) for item in block_ids)
        ):
            raise ValueError("guide_source_blocks_invalid")
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("guide_source_blocks_duplicate")
        if any(item not in available_block_ids for item in block_ids):
            raise ValueError("guide_source_block_unknown")
        return cls(text=text, source_block_ids=tuple(block_ids))

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "source_block_ids": list(self.source_block_ids),
        }


@dataclass(frozen=True, slots=True)
class ReadingGuide:
    research_question: tuple[GuideEntry, ...]
    key_methods: tuple[GuideEntry, ...]
    core_results: tuple[GuideEntry, ...]
    limitations: tuple[GuideEntry, ...]

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        available_block_ids: set[str],
    ) -> ReadingGuide:
        if not isinstance(value, dict):
            raise ValueError("reading_guide_invalid")
        _exact_keys(value, set(GUIDE_LIMITS))
        parsed: dict[str, tuple[GuideEntry, ...]] = {}
        for category, maximum in GUIDE_LIMITS.items():
            rows = value[category]
            if not isinstance(rows, list) or len(rows) > maximum:
                raise ValueError(f"guide_{category}_limit")
            parsed[category] = tuple(
                GuideEntry.from_dict(
                    row,
                    available_block_ids=available_block_ids,
                )
                for row in rows
            )
        if not any(parsed.values()):
            raise ValueError("reading_guide_empty")
        return cls(**parsed)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            category: [entry.to_dict() for entry in getattr(self, category)]
            for category in GUIDE_LIMITS
        }


@dataclass(frozen=True, slots=True)
class FullReviewHighlight:
    block_id: str
    kind: str
    reason: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FullReviewHighlight:
        if not isinstance(value, dict):
            raise ValueError("full_review_highlight_invalid")
        _exact_keys(value, {"block_id", "kind", "reason"})
        block_id = value["block_id"]
        if (
            not isinstance(block_id, str)
            or _MINERU_BLOCK_ID.fullmatch(block_id) is None
        ):
            raise ValueError("full_review_block_id_invalid")
        kind = value["kind"]
        if kind not in {"result", "method"}:
            raise ValueError("full_review_kind_invalid")
        reason = value["reason"]
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("full_review_reason_required")
        return cls(
            block_id=block_id,
            kind=kind,
            reason=reason.strip(),
        )


@dataclass(frozen=True, slots=True)
class FullReviewSubmission:
    contract_version: str
    highlights: tuple[FullReviewHighlight, ...]
    guide: ReadingGuide

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
        *,
        available_block_ids: set[str],
        substantive_block_count: int,
    ) -> FullReviewSubmission:
        if not isinstance(value, dict):
            raise ValueError("full_review_submission_invalid")
        _exact_keys(
            value,
            {"contract_version", "highlights", "guide"},
        )
        if value["contract_version"] != FULL_REVIEW_CONTRACT_VERSION:
            raise ValueError("full_review_contract_invalid")
        raw_highlights = value["highlights"]
        if not isinstance(raw_highlights, list):
            raise ValueError("full_review_highlights_invalid")
        highlights = tuple(
            FullReviewHighlight.from_dict(row)
            for row in raw_highlights
        )
        block_ids = [highlight.block_id for highlight in highlights]
        if len(set(block_ids)) != len(block_ids):
            raise ValueError("full_review_duplicate_block")
        if any(block_id not in available_block_ids for block_id in block_ids):
            raise ValueError("full_review_unknown_block")
        limit = int(substantive_block_count * 0.25)
        if len(highlights) > limit:
            raise ValueError("full_review_highlight_limit")
        guide = ReadingGuide.from_dict(
            value["guide"],
            available_block_ids=available_block_ids,
        )
        return cls(
            contract_version=FULL_REVIEW_CONTRACT_VERSION,
            highlights=highlights,
            guide=guide,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "highlights": [
                asdict(highlight)
                for highlight in self.highlights
            ],
            "guide": self.guide.to_dict(),
        }
