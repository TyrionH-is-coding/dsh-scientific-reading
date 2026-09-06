import json
from pathlib import Path

import pytest

from scientific_reading.metadata_enrichment import MetadataEnrichmentService, MetadataProviderRegistry, NCBIProvider, ProviderResult
from scientific_reading.models import PaperMetadata

class FakeProvider:
    def __init__(self, result): self.result = result; self.calls = []
    def fetch(self, metadata): self.calls.append(metadata); return self.result

def test_metadata_enrichment_uses_identifier_and_injects_abstract():
    fake = FakeProvider(ProviderResult.success({"title":"A","abstract_en":"One\n\nTwo","doi":"10.1/x"}))
    registry = MetadataProviderRegistry([fake])
    result = MetadataEnrichmentService(registry).enrich(PaperMetadata(title="工科假题录", doi="10.1/x"))
    assert result.status == "enriched"
    assert result.metadata.abstract_en == "One\n\nTwo"
    assert fake.calls

def test_metadata_enrichment_title_only_is_missing_without_provider_call():
    fake = FakeProvider(ProviderResult.success({"abstract_en":"bad"}))
    result = MetadataEnrichmentService(MetadataProviderRegistry([fake])).enrich(PaperMetadata(title="只有题名"))
    assert result.status == "missing"
    assert fake.calls == []


_CONTENT_FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "pubmed-content-v1.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CONTENT_FIXTURES["cases"], ids=lambda case: case["id"])
def test_ncbi_content_fidelity(case, monkeypatch):
    provider = NCBIProvider()
    requests = []

    def get_xml(url, accept):
        requests.append((url, accept))
        return case["xml"].encode("utf-8")

    monkeypatch.setattr(provider, "_get", get_xml)
    result = provider.fetch(PaperMetadata(pmid="12345678"))

    assert result.status == "success"
    assert result.metadata == {
        "pmid": "12345678",
        "title": case["title"],
        "abstract_en": case["abstract_en"],
    }
    assert requests == [(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=12345678&retmode=xml",
        "application/xml",
    )]


def test_ncbi_malformed_xml_remains_retry(monkeypatch):
    monkeypatch.setattr(NCBIProvider, "_get", lambda *args: b"<PubmedArticleSet>")
    result = NCBIProvider().fetch(PaperMetadata(pmid="12345678"))
    assert result == ProviderResult.retry("ncbi:ParseError")
