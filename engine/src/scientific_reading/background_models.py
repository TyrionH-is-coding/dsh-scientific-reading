from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass, field
from typing import Any


class AgentRequired(RuntimeError):
    def __init__(self, reason_code: str, required_input: dict[str, Any]) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.required_input = required_input


class UserRequired(RuntimeError):
    def __init__(self, reason_code: str, required_input: dict[str, Any]) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.required_input = required_input


class UserActionRequired(UserRequired):
    """精读流程需要用户提供 PDF 等外部输入。"""


@dataclass(frozen=True, slots=True, init=False)
class BackgroundRequest:
    paper_id: str
    target_stage: str
    input_hash: str
    _payload: dict[str, Any] = field(repr=False)

    def __init__(
        self,
        paper_id: str,
        target_stage: str,
        input_hash: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not paper_id.strip():
            raise ValueError("paper_id 不能为空")
        if not target_stage.strip():
            raise ValueError("target_stage 不能为空")
        if not re.fullmatch(r"[0-9a-f]{64}", input_hash):
            raise ValueError("input_hash 必须是小写 SHA-256")
        object.__setattr__(self, "paper_id", paper_id)
        object.__setattr__(self, "target_stage", target_stage)
        object.__setattr__(self, "input_hash", input_hash)
        object.__setattr__(self, "_payload", copy.deepcopy(payload or {}))

    @property
    def payload(self) -> dict[str, Any]:
        return copy.deepcopy(self._payload)

    def identity_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "target_stage": self.target_stage,
            "input_hash": self.input_hash,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BackgroundRequest:
        return cls(**value)


@dataclass(slots=True)
class JobStatus:
    job_id: str
    state: str
    created_at: str
    updated_at: str
    pid: int | None = None
    heartbeat_at: str | None = None
    reason_code: str | None = None
    required_input: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> JobStatus:
        return cls(**value)
