"""Stable-identifier metadata enrichment (metadata/abstract only)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Protocol

from .identifiers import normalize_arxiv, normalize_doi, normalize_pmid
from .models import PaperMetadata


@dataclass(frozen=True, slots=True)
class ProviderResult:
    status: str
    metadata: dict[str, Any]
    error: str | None = None

    @classmethod
    def success(cls, metadata: dict[str, Any]) -> "ProviderResult":
        return cls("success", metadata)

    @classmethod
    def missing(cls) -> "ProviderResult":
        return cls("missing", {})

    @classmethod
    def retry(cls, error: str) -> "ProviderResult":
        return cls("retry", {}, error)


class MetadataProvider(Protocol):
    def fetch(self, metadata: PaperMetadata) -> ProviderResult: ...


class MetadataProviderRegistry:
    def __init__(self, providers: list[MetadataProvider] | None = None) -> None:
        self.providers = list(providers) if providers is not None else [
            CrossrefProvider(), NCBIProvider(), ArxivProvider()
        ]

    def register(self, provider: MetadataProvider) -> None:
        self.providers.append(provider)

    def fetch(self, metadata: PaperMetadata) -> ProviderResult:
        if not (normalize_doi(metadata.doi) or normalize_pmid(metadata.pmid) or normalize_arxiv(metadata.source_url)):
            return ProviderResult.missing()
        for provider in self.providers:
            result = provider.fetch(metadata)
            if result.status in {"success", "retry"}:
                return result
        return ProviderResult.missing()


class _UrlProvider:
    def _get(self, url: str, accept: str) -> bytes:
        request = urllib.request.Request(
            url, headers={"Accept": accept, "User-Agent": "dsh-scientific-reading/0.1"}
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.read()


class CrossrefProvider(_UrlProvider):
    def fetch(self, metadata: PaperMetadata) -> ProviderResult:
        doi = normalize_doi(metadata.doi)
        if not doi:
            return ProviderResult.missing()
        try:
            raw = json.loads(self._get("https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"), "application/json"))
            item = raw.get("message", {})
            abstract = item.get("abstract")
            return ProviderResult.success({
                "title": (item.get("title") or [None])[0], "doi": item.get("DOI") or doi,
                "abstract_en": abstract,
                "year": ((item.get("published-print") or item.get("published-online") or {}).get("date-parts") or [[None]])[0][0],
                "journal": (item.get("container-title") or [None])[0],
            })
        except Exception as error:
            return ProviderResult.retry(f"crossref:{type(error).__name__}")


class NCBIProvider(_UrlProvider):
    def fetch(self, metadata: PaperMetadata) -> ProviderResult:
        pmid = normalize_pmid(metadata.pmid)
        if not pmid:
            return ProviderResult.missing()
        try:
            url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=" + pmid + "&retmode=xml"
            root = ET.fromstring(self._get(url, "application/xml"))
            text = " ".join(root.findall(".//AbstractText")[i].text or "" for i in range(len(root.findall(".//AbstractText"))))
            title = root.findtext(".//ArticleTitle")
            return ProviderResult.success({"pmid": pmid, "title": title, "abstract_en": text or None})
        except Exception as error:
            return ProviderResult.retry(f"ncbi:{type(error).__name__}")


class ArxivProvider(_UrlProvider):
    def fetch(self, metadata: PaperMetadata) -> ProviderResult:
        arxiv = normalize_arxiv(metadata.source_url)
        if not arxiv:
            return ProviderResult.missing()
        try:
            root = ET.fromstring(self._get("https://export.arxiv.org/api/query?id_list=" + urllib.parse.quote(arxiv), "application/atom+xml"))
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entry = root.find("a:entry", ns)
            if entry is None:
                return ProviderResult.missing()
            return ProviderResult.success({"title": entry.findtext("a:title", namespaces=ns), "abstract_en": entry.findtext("a:summary", namespaces=ns), "source_url": arxiv})
        except Exception as error:
            return ProviderResult.retry(f"arxiv:{type(error).__name__}")


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    status: str
    metadata: PaperMetadata
    error: str | None = None


class MetadataEnrichmentService:
    def __init__(self, registry: MetadataProviderRegistry | None = None) -> None:
        self.registry = registry or MetadataProviderRegistry()

    def enrich(self, metadata: PaperMetadata) -> EnrichmentResult:
        result = self.registry.fetch(metadata)
        if result.status == "missing":
            return EnrichmentResult("missing", metadata)
        if result.status == "retry":
            return EnrichmentResult("retry", metadata, result.error)
        values = metadata.to_dict()
        values.update({k: v for k, v in result.metadata.items() if v is not None})
        return EnrichmentResult("enriched", PaperMetadata.from_dict(values))
