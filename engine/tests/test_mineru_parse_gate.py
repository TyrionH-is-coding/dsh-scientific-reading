from scientific_reading.background_models import AgentRequired
from scientific_reading.mineru_api import MineruApiError
from scientific_reading.mineru_provider import MineruProviderError
from scientific_reading.reading_pipeline import raise_mineru_parse_gate


def test_provider_token_required_becomes_agent_gate() -> None:
    try:
        raise_mineru_parse_gate(MineruProviderError("mineru_api_token_required"))
    except AgentRequired as gate:
        assert gate.reason_code == "mineru_api_token_required"
        assert gate.required_input == {"stage": "parse_mineru"}
    else:
        raise AssertionError("provider token errors must become waiting_agent")


def test_api_auth_failure_stays_an_agent_gate() -> None:
    try:
        raise_mineru_parse_gate(MineruApiError("mineru_api_auth_failed"))
    except AgentRequired as gate:
        assert gate.reason_code == "mineru_api_auth_failed"
    else:
        raise AssertionError("api auth errors must remain recoverable")
