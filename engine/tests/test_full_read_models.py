from __future__ import annotations

import pytest

from scientific_reading.full_read_models import (
    FULL_REVIEW_CONTRACT_VERSION,
    FULL_TRANSLATION_CONTRACT_VERSION,
    FullReviewSubmission,
    Translation,
    TranslationBatchSubmission,
)


def test_translation_contract_keeps_source_and_highlight() -> None:
    submission = TranslationBatchSubmission.from_dict(
        {
            "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
            "batch_id": "batch-0001",
            "source_sha256": "a" * 64,
            "translations": [
                {
                    "block_id": "p0001-m0001",
                    "source_text": "A synthetic bridge result.",
                    "translation_zh": "一项合成桥梁结果。",
                    "highlight": "result",
                }
            ],
        },
        expected_blocks=(
            {
                "block_id": "p0001-m0001",
                "english": "A synthetic bridge result.",
                "source_type": "text",
            },
        ),
        expected_batch_id="batch-0001",
        expected_source_sha256="a" * 64,
    )

    assert submission.translations[0].source_text == "A synthetic bridge result."
    assert submission.translations[0].translation_zh == "一项合成桥梁结果。"
    assert submission.translations[0].highlight == "result"


def test_translation_v3_accepts_result_method_and_none() -> None:
    source = "The proposed scheduler reduced mean delay by 18%."
    for kind in ("result", "method", "none"):
        row = Translation.from_dict(
            {
                "block_id": "p0001-m0001",
                "source_text": source,
                "translation_zh": "该调度器将平均延迟降低了18%。",
                "highlight": kind,
            },
            expected_source_text=source,
            reference=False,
        )
        assert row.highlight == kind


def test_translation_v3_rejects_primary_secondary() -> None:
    for kind in ("primary", "secondary"):
        with pytest.raises(ValueError, match="translation_highlight_invalid"):
            Translation.from_dict(
                {
                    "block_id": "p0001-m0001",
                    "source_text": "Method text.",
                    "translation_zh": "方法文本。",
                    "highlight": kind,
                },
                expected_source_text="Method text.",
                reference=False,
            )


def test_translation_contract_rejects_source_text_or_sha_mismatch() -> None:
    base = {
        "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
        "batch_id": "batch-0001",
        "source_sha256": "b" * 64,
        "translations": [
            {
                "block_id": "p0001-m0001",
                "source_text": "changed",
                "translation_zh": "译文",
                "highlight": "none",
            }
        ],
    }
    with pytest.raises(ValueError, match="translation_source_sha_mismatch"):
        TranslationBatchSubmission.from_dict(
            base,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "original",
                    "source_type": "text",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )
    base["source_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="translation_source_text_mismatch"):
        TranslationBatchSubmission.from_dict(
            base,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "original",
                    "source_type": "text",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )


def test_reference_translation_may_be_empty_but_caption_may_not() -> None:
    reference = {
        "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
        "batch_id": "batch-0001",
        "source_sha256": "a" * 64,
        "translations": [
            {
                "block_id": "p0001-m0001",
                "source_text": "[1] Synthetic reference.",
                "translation_zh": "",
                "highlight": "none",
            }
        ],
    }
    TranslationBatchSubmission.from_dict(
        reference,
        expected_blocks=(
            {
                "block_id": "p0001-m0001",
                "english": "[1] Synthetic reference.",
                "source_type": "reference",
            },
        ),
        expected_batch_id="batch-0001",
        expected_source_sha256="a" * 64,
    )
    reference["translations"][0]["translation_zh"] = "不应翻译"
    with pytest.raises(ValueError, match="reference_translation_forbidden"):
        TranslationBatchSubmission.from_dict(
            reference,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "[1] Synthetic reference.",
                    "source_type": "reference",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )
    reference["translations"][0]["translation_zh"] = ""
    reference["translations"][0]["highlight"] = "result"
    with pytest.raises(ValueError, match="reference_highlight_forbidden"):
        TranslationBatchSubmission.from_dict(
            reference,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "[1] Synthetic reference.",
                    "source_type": "reference",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match="translation_zh_required"):
        reference["translations"][0]["source_text"] = (
            "Figure 1. Synthetic bridge."
        )
        TranslationBatchSubmission.from_dict(
            reference,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "Figure 1. Synthetic bridge.",
                    "source_type": "caption",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )


def _translation_payload(block_ids=("p0001-m0001", "p0001-m0002")):
    return {
        "contract_version": FULL_TRANSLATION_CONTRACT_VERSION,
        "batch_id": "batch-0001",
        "source_sha256": "a" * 64,
        "translations": [
            {
                "block_id": block_id,
                "source_text": f"Synthetic engineering source {index}",
                "translation_zh": f"合成工程译文 {index}",
                "highlight": "none",
            }
            for index, block_id in enumerate(block_ids, start=1)
        ],
    }


def test_translation_batch_accepts_exact_order_and_round_trips() -> None:
    expected = ("p0001-m0001", "p0001-m0002")
    payload = _translation_payload(expected)

    submission = TranslationBatchSubmission.from_dict(
        payload,
        expected_blocks=tuple(
            {
                "block_id": block_id,
                "english": f"Synthetic engineering source {index}",
                "source_type": "text",
            }
            for index, block_id in enumerate(expected, start=1)
        ),
        expected_batch_id="batch-0001",
        expected_source_sha256="a" * 64,
    )

    assert submission.to_dict() == payload
    assert FULL_TRANSLATION_CONTRACT_VERSION == "full-translation-v3"


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (
            lambda value: value.update({"extra": True}),
            "unexpected_keys",
        ),
        (
            lambda value: value.update({"contract_version": "old"}),
            "translation_contract_invalid",
        ),
        (
            lambda value: value.update({"batch_id": "batch-0002"}),
            "translation_batch_mismatch",
        ),
        (
            lambda value: value["translations"].reverse(),
            "translation_block_order_mismatch",
        ),
        (
            lambda value: value["translations"][0].update({"translation_zh": " "}),
            "translation_zh_required",
        ),
        (
            lambda value: value["translations"][0].update(
                {"block_id": "p0001-b0001"}
            ),
            "translation_block_id_invalid",
        ),
        (
            lambda value: value["translations"][0].update({"highlight": "green"}),
            "translation_highlight_invalid",
        ),
    ],
)
def test_translation_batch_rejects_invalid_values(mutate, error) -> None:
    payload = _translation_payload()
    mutate(payload)

    with pytest.raises(ValueError, match=error):
        TranslationBatchSubmission.from_dict(
            payload,
            expected_blocks=(
                {
                    "block_id": "p0001-m0001",
                    "english": "Synthetic engineering source 1",
                    "source_type": "text",
                },
                {
                    "block_id": "p0001-m0002",
                    "english": "Synthetic engineering source 2",
                    "source_type": "text",
                },
            ),
            expected_batch_id="batch-0001",
            expected_source_sha256="a" * 64,
        )


def _review_payload(block_ids=("p0002-m0001",)):
    return {
        "contract_version": FULL_REVIEW_CONTRACT_VERSION,
        "highlights": [
            {
                "block_id": block_id,
                "kind": "result",
                "reason": "该段限定了合成载荷结论的适用边界。",
            }
            for block_id in block_ids
        ],
        "guide": {
            "research_question": [
                {
                    "text": "合成载荷结果在什么边界条件下成立？",
                    "source_block_ids": ["p0001-m0001"],
                }
            ],
            "key_methods": [],
            "core_results": [
                {
                    "text": "合成载荷结果仅适用于所述边界条件。",
                    "source_block_ids": ["p0002-m0001"],
                }
            ],
            "limitations": [],
        },
    }


def test_full_review_accepts_known_blocks_within_limit() -> None:
    payload = _review_payload(("p0002-m0001", "p0003-m0001"))

    submission = FullReviewSubmission.from_dict(
        payload,
        available_block_ids={
            "p0001-m0001",
            "p0002-m0001",
            "p0003-m0001",
        },
        substantive_block_count=25,
    )

    assert submission.to_dict() == payload


def test_full_review_v2_validates_guide_sources_and_limits() -> None:
    review = FullReviewSubmission.from_dict(
        {
            "contract_version": "full-review-v2",
            "highlights": [
                {
                    "block_id": "p0001-m0002",
                    "kind": "result",
                    "reason": "核心定量结果",
                }
            ],
            "guide": {
                "research_question": [
                    {
                        "text": "如何在资源受限时降低车间调度延迟？",
                        "source_block_ids": ["p0001-m0001"],
                    }
                ],
                "key_methods": [],
                "core_results": [
                    {
                        "text": "平均延迟降低18%。",
                        "source_block_ids": ["p0001-m0002"],
                    }
                ],
                "limitations": [],
            },
        },
        available_block_ids={"p0001-m0001", "p0001-m0002"},
        substantive_block_count=8,
    )

    assert review.guide.core_results[0].source_block_ids == (
        "p0001-m0002",
    )
    assert review.highlights[0].kind == "result"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (
            _review_payload(("p9999-m0001",)),
            "full_review_unknown_block",
        ),
        (
            _review_payload(("p0002-m0001", "p0002-m0001")),
            "full_review_duplicate_block",
        ),
        (
            {
                **_review_payload(),
                "highlights": [
                    {
                        "block_id": "p0002-m0001",
                        "kind": "primary",
                        "reason": "wrong kind",
                    }
                ],
            },
            "full_review_kind_invalid",
        ),
        (
            {
                **_review_payload(),
                "guide": {
                    **_review_payload()["guide"],
                    "core_results": [
                        {
                            "text": "",
                            "source_block_ids": ["p0002-m0001"],
                        }
                    ],
                },
            },
            "guide_text_required",
        ),
    ],
)
def test_full_review_rejects_invalid_values(payload, error) -> None:
    with pytest.raises(ValueError, match=error):
        FullReviewSubmission.from_dict(
            payload,
            available_block_ids={
                "p0001-m0001",
                "p0002-m0001",
                "p0003-m0001",
            },
            substantive_block_count=25,
        )


def test_full_review_enforces_twenty_five_percent_limit_with_minimum_one() -> None:
    payload = _review_payload(
        ("p0001-m0001", "p0002-m0001", "p0003-m0001")
    )

    with pytest.raises(ValueError, match="full_review_highlight_limit"):
        FullReviewSubmission.from_dict(
            payload,
            available_block_ids={
                "p0001-m0001",
                "p0002-m0001",
                "p0003-m0001",
            },
            substantive_block_count=9,
        )


def _review_with_guide(guide: dict) -> dict:
    payload = _review_payload(())
    payload["guide"] = guide
    return payload


@pytest.mark.parametrize(
    ("guide", "error"),
    [
        (
            {
                **_review_payload()["guide"],
                "unknown": [],
            },
            "unexpected_keys",
        ),
        (
            {
                **_review_payload()["guide"],
                "research_question": [
                    {
                        "text": "问题",
                        "source_block_ids": ["p9999-m9999"],
                    }
                ],
            },
            "guide_source_block_unknown",
        ),
        (
            {
                **_review_payload()["guide"],
                "research_question": [
                    {"text": "问题", "source_block_ids": []}
                ],
            },
            "guide_source_blocks_invalid",
        ),
        (
            {
                **_review_payload()["guide"],
                "research_question": [
                    {
                        "text": "问题",
                        "source_block_ids": [
                            "p0001-m0001",
                            "p0001-m0001",
                        ],
                    }
                ],
            },
            "guide_source_blocks_duplicate",
        ),
        (
            {
                **_review_payload()["guide"],
                "research_question": [
                    {
                        "text": "过长" * 121,
                        "source_block_ids": ["p0001-m0001"],
                    }
                ],
            },
            "guide_text_too_long",
        ),
        (
            {
                **_review_payload()["guide"],
                "research_question": [
                    {
                        "text": "问题一",
                        "source_block_ids": ["p0001-m0001"],
                    },
                    {
                        "text": "问题二",
                        "source_block_ids": ["p0002-m0001"],
                    },
                ],
            },
            "guide_research_question_limit",
        ),
        (
            {
                **_review_payload()["guide"],
                "key_methods": [
                    {
                        "text": f"方法 {index}",
                        "source_block_ids": ["p0001-m0001"],
                    }
                    for index in range(3)
                ],
            },
            "guide_key_methods_limit",
        ),
        (
            {
                **_review_payload()["guide"],
                "core_results": [
                    {
                        "text": f"结果 {index}",
                        "source_block_ids": ["p0002-m0001"],
                    }
                    for index in range(4)
                ],
            },
            "guide_core_results_limit",
        ),
        (
            {
                **_review_payload()["guide"],
                "limitations": [
                    {
                        "text": f"局限 {index}",
                        "source_block_ids": ["p0002-m0001"],
                    }
                    for index in range(3)
                ],
            },
            "guide_limitations_limit",
        ),
        (
            {
                "research_question": [],
                "key_methods": [],
                "core_results": [],
                "limitations": [],
            },
            "reading_guide_empty",
        ),
    ],
)
def test_full_review_rejects_invalid_guide(guide, error) -> None:
    with pytest.raises(ValueError, match=error):
        FullReviewSubmission.from_dict(
            _review_with_guide(guide),
            available_block_ids={"p0001-m0001", "p0002-m0001"},
            substantive_block_count=25,
        )
