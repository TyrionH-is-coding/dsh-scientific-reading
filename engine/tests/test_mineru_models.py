from copy import deepcopy

import pytest

from scientific_reading.mineru_models import (
    MINERU_NORMALIZATION_VERSION,
    MineruContentItem,
)


def test_text_item_round_trip() -> None:
    value = {
        "type": "text",
        "text": "Engineering load response",
        "text_level": 2,
        "bbox": [72, 80, 520, 110],
        "page_idx": 0,
    }

    item = MineruContentItem.from_dict(value, index=7)

    assert MINERU_NORMALIZATION_VERSION == "mineru-normalization-v3"
    assert item.index == 7
    assert item.page == 1
    assert item.text == "Engineering load response"
    assert item.to_dict()["bbox"] == [72.0, 80.0, 520.0, 110.0]


def test_empty_text_placeholder_is_preserved_without_body() -> None:
    item = MineruContentItem.from_dict(
        {
            "type": "text",
            "text": "   ",
            "bbox": [154, 330, 851, 402],
            "page_idx": 0,
        },
        index=5,
    )

    assert item.text is None
    assert item.supported is True


@pytest.mark.parametrize(
    "value",
    [
        {
            "type": "image",
            "img_path": "images/figure.jpg",
            "image_caption": ["Figure 1", "Load response"],
            "image_footnote": [],
            "bbox": [10, 20, 300, 400],
            "page_idx": 1,
        },
        {
            "type": "table",
            "img_path": "images/table.jpg",
            "table_caption": ["Table 1"],
            "table_footnote": ["Synthetic test"],
            "table_body": "<table><tr><td>1</td></tr></table>",
            "bbox": [10, 20, 300, 400],
            "page_idx": 2,
        },
        {
            "type": "list",
            "sub_type": "ordered",
            "list_items": ["first", "second"],
            "bbox": [10, 20, 300, 400],
            "page_idx": 3,
        },
    ],
)
def test_supported_structured_items(value: dict) -> None:
    item = MineruContentItem.from_dict(value, index=1)

    assert item.page == value["page_idx"] + 1
    assert item.item_type == value["type"]


def test_unknown_type_is_preserved_for_warning() -> None:
    item = MineruContentItem.from_dict(
        {
            "type": "equation_group",
            "bbox": [10, 20, 300, 400],
            "page_idx": 0,
        },
        index=4,
    )

    assert item.supported is False
    assert item.item_type == "equation_group"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"page_idx": -1}, "page_idx"),
        ({"bbox": [0, 1, 2]}, "bbox"),
        ({"img_path": "../outside.png"}, "img_path"),
        ({"img_path": "C:/outside.png"}, "img_path"),
    ],
)
def test_invalid_text_or_asset_values_are_rejected(
    change,
    message,
) -> None:
    base = {
        "type": "text",
        "text": "Engineering evidence",
        "bbox": [10, 20, 300, 400],
        "page_idx": 0,
    }
    value = deepcopy(base)
    value.update(change)
    if "img_path" in change:
        value["type"] = "image"
        value.pop("text", None)

    with pytest.raises(ValueError, match=message):
        MineruContentItem.from_dict(value, index=0)
