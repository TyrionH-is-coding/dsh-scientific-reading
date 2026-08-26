import inspect

from scientific_reading.mineru_service import MineruParseResult, MineruParseService
from scientific_reading.reading_pipeline_models import PIPELINE_STAGES
from scientific_reading.worker import DEFAULT_HANDLERS


def test_mineru_service_has_no_local_runner_or_executable_contract() -> None:
    assert "runner" not in inspect.signature(MineruParseService).parameters
    assert "executable" not in inspect.signature(MineruParseService.run).parameters
    assert MineruParseResult.__dataclass_fields__["provider"].default == "mineru-api-v4"


def test_full_read_pipeline_uses_only_mineru_api_parse_stage() -> None:
    assert PIPELINE_STAGES == (
        "ensure_pdf",
        "parse_mineru",
        "translate_full",
        "render_reader",
        "schedule_derived_updates",
    )
    assert set(DEFAULT_HANDLERS) == {
        "metadata_enrichment",
        "abstract_read",
        "xlsx_snapshot",
        "full_read",
        "feishu_sync",
        "full_read_pipeline",
    }
