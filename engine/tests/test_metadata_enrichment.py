from scientific_reading.metadata_enrichment import MetadataEnrichmentService, MetadataProviderRegistry, ProviderResult
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
