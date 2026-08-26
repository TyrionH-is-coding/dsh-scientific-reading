from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Literal


NextAction = Literal["done", "poll", "agent", "user"]


@dataclass(frozen=True, slots=True)
class ForegroundResult:
    paper_id: str
    status: str
    job_id: str | None
    foreground_elapsed_ms: int
    agent_required: bool
    next_action: NextAction
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.foreground_elapsed_ms < 0:
            raise ValueError("foreground_elapsed_ms 不能为负数")
        if self.next_action not in {"done", "poll", "agent", "user"}:
            raise ValueError("next_action 无效")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ForegroundTimer:
    def __init__(self, clock_ns: Callable[[], int] = time.perf_counter_ns) -> None:
        self.clock_ns = clock_ns
        self.started_ns = clock_ns()

    def finish(self, **values: Any) -> ForegroundResult:
        elapsed_ms = max(0, (self.clock_ns() - self.started_ns) // 1_000_000)
        return ForegroundResult(foreground_elapsed_ms=elapsed_ms, **values)
