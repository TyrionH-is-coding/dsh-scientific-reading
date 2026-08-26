from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PIPELINE_STAGES = (
    "ensure_pdf",
    "parse_mineru",
    "translate_full",
    "render_reader",
    "schedule_derived_updates",
)

USER_STATUS = {
    "queued": "精读排队",
    "ensure_pdf": "获取 PDF",
    "parse_mineru": "解析全文",
    "translate_full": "翻译与生成",
    "render_reader": "翻译与生成",
    "completed": "精读完成",
    "needs_user": "需要用户处理",
    "failed": "处理失败",
}


@dataclass(slots=True)
class ReadingPipelineState:
    paper_id: str
    parent_job_id: str
    current_stage: str = "ensure_pdf"
    state: str = "queued"
    stage_jobs: dict[str, str] = field(default_factory=dict)
    stage_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    stage_timings: dict[str, dict[str, str | None]] = field(default_factory=dict)
    source_pdf_sha256: str | None = None
    reader_source_sha256: str | None = None
    required_action: dict[str, Any] | None = None
    last_error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    completed_at: str | None = None
    contract_version: str = "reading-pipeline-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReadingPipelineState":
        return cls(**value)


PipelineResult = ReadingPipelineState
