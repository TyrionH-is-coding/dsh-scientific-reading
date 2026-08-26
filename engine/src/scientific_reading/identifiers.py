from __future__ import annotations

import hashlib
import re
import unicodedata

from .models import PaperMetadata


DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
ARXIV_PREFIX = re.compile(
    r"^(?:https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/|arxiv:\s*)",
    re.IGNORECASE,
)
ARXIV_ID = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z-]+)?/\d{7})(?:v\d+)?$",
    re.IGNORECASE,
)
WINDOWS_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]+')
MAX_COMPONENT_LENGTH = 120


def normalize_doi(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    return DOI_PREFIX.sub("", value.strip()).strip().lower() or None


def normalize_pmid(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    normalized = re.sub(r"^pmid:\s*", "", value.strip(), flags=re.IGNORECASE)
    return normalized if normalized.isdigit() else None


def normalize_arxiv(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    normalized = re.sub(
        r"\.pdf$", "", ARXIV_PREFIX.sub("", value.strip()), flags=re.IGNORECASE
    )
    if not ARXIV_ID.fullmatch(normalized):
        return None
    return re.sub(r"v\d+$", "", normalized, flags=re.IGNORECASE).casefold()


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def metadata_identity_anchor_found(
    text: str,
    metadata: PaperMetadata,
) -> bool:
    """Verify identity from normalized parser output, never raw PDF bytes."""
    normalized_text = normalize_title(text)
    title = normalize_title(metadata.title)
    if title and title in normalized_text:
        return True
    if doi := normalize_doi(metadata.doi):
        if doi in text.casefold():
            return True
    if pmid := normalize_pmid(metadata.pmid):
        if pmid in text:
            return True
    return False


def normalize_author(value: str) -> str:
    return normalize_title(value)


def metadata_identity_compatible(
    stored: PaperMetadata,
    current: PaperMetadata,
) -> bool:
    stored_ids = (
        normalize_doi(stored.doi),
        normalize_pmid(stored.pmid),
        normalize_arxiv(stored.source_url),
    )
    current_ids = (
        normalize_doi(current.doi),
        normalize_pmid(current.pmid),
        normalize_arxiv(current.source_url),
    )
    shared_match = False
    for stored_id, current_id in zip(stored_ids, current_ids, strict=True):
        if stored_id is not None and current_id is not None:
            if stored_id != current_id:
                return False
            shared_match = True
    if shared_match:
        return True
    stored_title = normalize_title(stored.title)
    current_title = normalize_title(current.title)
    return bool(stored_title and stored_title == current_title)


def _paper_id_component(prefix: str, value: str) -> str | None:
    safe_value = WINDOWS_UNSAFE.sub("_", value).strip(" ._")
    if not safe_value:
        return None
    paper_id = f"{prefix}{safe_value}"
    if len(paper_id) <= MAX_COMPONENT_LENGTH:
        return paper_id
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    available = MAX_COMPONENT_LENGTH - len(prefix) - len(digest) - 1
    truncated = safe_value[:available].rstrip(" ._")
    return f"{prefix}{truncated}_{digest}"


def stable_paper_id(metadata: PaperMetadata) -> str:
    if pmid := normalize_pmid(metadata.pmid):
        if paper_id := _paper_id_component("pmid_", pmid):
            return paper_id
    if doi := normalize_doi(metadata.doi):
        if paper_id := _paper_id_component("doi_", doi):
            return paper_id
    if arxiv := normalize_arxiv(metadata.source_url):
        if paper_id := _paper_id_component("arxiv_", arxiv):
            return paper_id
    if metadata.library_key:
        safe_key = re.sub(r"[^A-Za-z0-9_-]+", "_", metadata.library_key)
        if paper_id := _paper_id_component("library_", safe_key):
            return paper_id

    first_author = normalize_author(metadata.authors[0]) if metadata.authors else ""
    fingerprint = (
        f"{normalize_title(metadata.title)}|{metadata.year or ''}|{first_author}"
    )
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"title_{digest}"
