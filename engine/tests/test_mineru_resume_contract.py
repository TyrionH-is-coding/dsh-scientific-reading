from types import SimpleNamespace

import pytest

from scientific_reading.__main__ import _validate_full_read_resume


@pytest.mark.parametrize("reason", [
    "mineru_runtime_required", "mineru_provider_unavailable",
    "mineru_local_unavailable", "mineru_api_token_required",
    "mineru_api_auth_failed", "mineru_api_quota_exceeded",
    "mineru_api_timeout", "mineru_api_unavailable",
])
def test_configured_mineru_gate_resumes_without_credentials_in_job_input(reason):
    status = SimpleNamespace(state="waiting_agent", reason_code=reason)
    assert _validate_full_read_resume(status, {}) == {}
    with pytest.raises(ValueError, match="mineru_resume_input_invalid"):
        _validate_full_read_resume(status, {"api_key": "must-not-enter-job"})
