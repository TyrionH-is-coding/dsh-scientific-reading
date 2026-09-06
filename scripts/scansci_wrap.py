"""A 的固定 OA 下载入口：仅 arXiv / Europe PMC OA / 显式邮箱 Unpaywall，不加载机构配置或综合 fetch。"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import importlib.util
from importlib.metadata import version
import json
import os
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path
from urllib.parse import quote, unquote


def _manual(reason: str = "oa_pdf_unavailable") -> dict:
    return {
        "status": "manual_required", "quality": "none", "reason": reason,
        "next_action": {"kind": "local_pdf", "message": "未取得 OA PDF，请补入本地 PDF 后继续。"},
    }


def _load_oa_sources():
    # 固定依赖的两个 __init__ 会载入全来源注册并改代理/CA；只加载 OA 所需模块。
    if "scansci_pdf" not in sys.modules:
        spec = importlib.util.find_spec("scansci_pdf")
        if spec is None or not spec.submodule_search_locations:
            raise ImportError("scansci_pdf_missing")
        package = types.ModuleType("scansci_pdf")
        package.__path__ = list(spec.submodule_search_locations)
        package.__spec__ = spec
        sys.modules["scansci_pdf"] = package
    if "scansci_pdf.sources" not in sys.modules:
        sources = types.ModuleType("scansci_pdf.sources")
        sources.__path__ = [str(Path(location) / "sources") for location in sys.modules["scansci_pdf"].__path__]
        sys.modules["scansci_pdf.sources"] = sources
    from scansci_pdf.identifiers import normalize_arxiv_id
    from scansci_pdf.sources import arxiv, unpaywall
    return normalize_arxiv_id, arxiv, unpaywall


def _fetch_oa(identifier: str, output_dir: Path) -> dict:
    normalize_arxiv_id, arxiv, unpaywall = _load_oa_sources()

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    arxiv_id = normalize_arxiv_id(identifier)
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", unquote(identifier), re.I)
    doi = match.group(0) if match else ""
    if not arxiv_id and not doi:
        return _manual("oa_identifier_required")
    # 不读取 ScanSci 用户配置、缓存或登录态；旧模型/环境参数不能拓宽来源。
    config = {"download_strategy": "oa_only",
              "network_proxy": os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "",
              "connect_timeout": 5, "read_timeout": 20, "max_unpaywall_candidates": 2}
    email = os.environ.get("UNPAYWALL_EMAIL", "").strip()
    if email:
        config["email"] = email
    with tempfile.TemporaryDirectory(prefix=".scansci-", dir=output_dir) as temporary:
        staging = Path(temporary) / "source.pdf"
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                if arxiv_id:
                    result = arxiv.try_arxiv(arxiv_id, staging, config)
                    source_name = "arxiv"
                else:
                    result = unpaywall.try_unpaywall(doi, staging, config) if email else None
                    source_name = "open_access"
                    if not result or result.get("success") is False:
                        result = _europe_pmc_oa(doi, staging, config)
                        source_name = "europe_pmc_oa"
            if not isinstance(result, dict) or result.get("success") is False:
                return _manual()
            source = Path(str(result.get("path") or result.get("file") or "")).resolve()
            if not source.is_file() or not source.is_relative_to(Path(temporary).resolve()):
                return _manual("oa_pdf_invalid")
            contents = source.read_bytes()
            if len(contents) < 1000 or not contents.startswith(b"%PDF-") or b"%%EOF" not in contents[-1024:]:
                return _manual("oa_pdf_invalid")
            target = output_dir / (hashlib.sha256(contents).hexdigest() + ".pdf")
            if not target.is_file():
                shutil.copyfile(source, target)
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(contents).digest():
                return _manual("oa_pdf_readback_failed")
            return {"status": "success", "quality": "pdf_only", "paper": {
                "doi": doi, "pdf_path": str(target), "source": source_name,
                "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else f"https://doi.org/{doi}",
            }}
        except Exception:
            return _manual()


def _europe_pmc_oa(doi: str, destination: Path, config: dict):
    from scansci_pdf.network import fetch_json
    from scansci_pdf.pdf_utils import download_pdf

    query = quote(f'DOI:"{doi}" AND OPEN_ACCESS:Y')
    payload = fetch_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={query}&format=json&resultType=core&pageSize=3", config)
    for paper in (payload or {}).get("resultList", {}).get("result", []):
        if paper.get("isOpenAccess") != "Y":
            continue
        for link in paper.get("fullTextUrlList", {}).get("fullTextUrl", [])[:4]:
            if link.get("availabilityCode") != "OA" or link.get("documentStyle") != "pdf":
                continue
            result = download_pdf(link.get("url", ""), destination, config, "EuropePMC OA", require_pdf_like_url=False)
            if result:
                return result
    return None


def _provider_mode() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict) or set(payload) != {"identifier", "destination", "legal_only"}:
            raise ValueError("provider_request_invalid")
        identifier = payload["identifier"]
        destination = Path(payload["destination"])
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("provider_identifier_invalid")
        if payload["legal_only"] is not True:
            raise ValueError("legal_only_required")
        if not destination.is_absolute() or destination.suffix.lower() != ".pdf":
            raise ValueError("provider_destination_invalid")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".scansci-", dir=destination.parent) as temporary:
            result = _fetch_oa(identifier, Path(temporary))
            if result["status"] != "success":
                print(json.dumps(result, ensure_ascii=False))
                return 4
            shutil.copyfile(result["paper"]["pdf_path"], destination)
        print(json.dumps({"status": "success", "path": str(destination.resolve())}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, OSError, ImportError):
        print(json.dumps(_manual("oa_provider_failed"), ensure_ascii=False))
        return 4


def main() -> int:
    if sys.argv[1:] == ["check"]:
        try:
            _load_oa_sources()
            installed = version("scansci-pdf")
            if installed != "1.9.0":
                raise ImportError("scansci_version_unsupported")
            print(json.dumps({"status": "ready", "version": installed, "mode": "oa_only"}))
            return 0
        except ImportError:
            print(json.dumps({"status": "unavailable", "mode": "oa_only"}))
            return 4
    if len(sys.argv) == 1:
        return _provider_mode()
    parser = argparse.ArgumentParser(description="OA-only PDF 获取")
    parser.add_argument("command", choices=["fetch"])
    parser.add_argument("identifier")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--format", choices=["json"], default="json")
    args = parser.parse_args()
    try:
        result = _fetch_oa(args.identifier, args.output)
    except (ImportError, OSError):
        result = _manual("oa_provider_unavailable")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "success" else 4


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
