import hashlib, json
from scientific_reading.abstract_read_service import AbstractReadService, AbstractReadValidationError
from scientific_reading.models import PaperMetadata
from scientific_reading.workspace import PaperWorkspace

def test_abstract_read_normalizes_html_and_preserves_paragraphs(tmp_path):
    metadata = PaperMetadata(title="Fake engineering paper", doi="10.1/x", abstract_en="<p>First <b>paragraph</b>.</p>\n<p>Second.</p>")
    workspace = PaperWorkspace.create(tmp_path, metadata)
    service = AbstractReadService()
    context = service.inspect(workspace)
    assert [p["source_en"] for p in context["paragraphs"]] == ["First paragraph.", "Second."]
    assert context["source_sha256"] == hashlib.sha256(b"First paragraph.\n\nSecond.").hexdigest()

def test_publish_rejects_stale_or_mismatched_translation(tmp_path):
    metadata = PaperMetadata(title="Fake engineering paper", doi="10.1/x", abstract_en="One\n\nTwo")
    workspace = PaperWorkspace.create(tmp_path, metadata)
    service = AbstractReadService()
    context = service.inspect(workspace)
    payload = {"contract_version":"abstract-translation-v1", "source_sha256":context["source_sha256"], "paragraphs":[{"index":0,"source_en":"One","translation_zh":"一"},{"index":1,"source_en":"Two","translation_zh":"二"}]}
    result = service.publish(workspace, payload)
    assert result["status"] == "abstract_read_ready"
    assert json.loads((workspace.reading_dir / "abstract_read.json").read_text(encoding="utf-8"))["paragraphs"][1]["translation_zh"] == "二"
    payload["source_sha256"] = "0" * 64
    try: service.publish(workspace, payload)
    except AbstractReadValidationError as e: assert "source_sha256" in str(e)
    else: raise AssertionError("expected stale rejection")

def test_missing_abstract_has_no_agent_gate(tmp_path):
    workspace = PaperWorkspace.create(tmp_path, PaperMetadata(title="Missing", doi="10.1/m"))
    assert AbstractReadService().inspect(workspace)["status"] == "missing"
