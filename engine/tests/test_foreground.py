import pytest

from scientific_reading.foreground import ForegroundResult, ForegroundTimer


def test_foreground_result_uses_monotonic_elapsed_and_fixed_actions() -> None:
    clock = iter([1_000_000_000, 1_184_000_000]).__next__
    timer = ForegroundTimer(clock_ns=clock)

    result = timer.finish(
        paper_id="doi_10.5555_bridge.1",
        status="queued",
        job_id="job_ab12cd34ef56",
        agent_required=False,
        next_action="poll",
    )

    assert result.foreground_elapsed_ms == 184
    assert result.to_dict() == {
        "paper_id": "doi_10.5555_bridge.1",
        "status": "queued",
        "job_id": "job_ab12cd34ef56",
        "foreground_elapsed_ms": 184,
        "agent_required": False,
        "next_action": "poll",
        "detail": {},
    }


@pytest.mark.parametrize("next_action", ["wait", "retry", "unknown"])
def test_foreground_result_rejects_undefined_next_action(next_action) -> None:
    with pytest.raises(ValueError, match="next_action"):
        ForegroundResult(
            paper_id="paper",
            status="queued",
            job_id=None,
            foreground_elapsed_ms=0,
            agent_required=False,
            next_action=next_action,
        )


def test_foreground_result_rejects_negative_elapsed_time() -> None:
    with pytest.raises(ValueError, match="foreground_elapsed_ms"):
        ForegroundResult(
            paper_id="paper",
            status="failed",
            job_id=None,
            foreground_elapsed_ms=-1,
            agent_required=False,
            next_action="done",
        )
