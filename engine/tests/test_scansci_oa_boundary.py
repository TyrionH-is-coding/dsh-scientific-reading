from __future__ import annotations

import importlib.util
import hashlib
import io
import json
import sys
import types
from pathlib import Path

import pytest


def load_wrapper(monkeypatch, download):
    """替身只替换外部来源；固定入口和文件检查执行真实代码。"""
    monkeypatch.setenv("UNPAYWALL_EMAIL", "fixture@example.org")
    package = types.ModuleType("scansci_pdf")
    package.__path__ = []
    sources = types.ModuleType("scansci_pdf.sources")
    sources.__path__ = []
    arxiv = types.ModuleType("scansci_pdf.sources.arxiv")
    arxiv.try_arxiv = download
    arxiv.download_arxiv_pdf = download
    unpaywall = types.ModuleType("scansci_pdf.sources.unpaywall")
    unpaywall.try_unpaywall = download
    identifiers = types.ModuleType("scansci_pdf.identifiers")
    identifiers.normalize_arxiv_id = lambda value: "1706.03762" if "1706.03762" in value else None
    identifiers.normalize_doi = lambda value: value.removeprefix("https://doi.org/")
    # 旧 wrapper 可以载入；真正失败应是缺失固定 OA 入口。
    auth = types.ModuleType("scansci_pdf.auth")
    auth.WebVPNAuth = type("WebVPNAuth", (), {"login": lambda self, force=False: pytest.fail("institution login")})
    main = types.ModuleType("scansci_pdf.main")
    main.app = lambda **kwargs: pytest.fail("generic ScanSci CLI must not run")
    for module in (package, sources, arxiv, unpaywall, identifiers, auth, main):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    path = Path(__file__).resolve().parents[2] / "scripts" / "scansci_wrap.py"
    spec = importlib.util.spec_from_file_location("scansci_oa_wrapper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(getattr(module, "_fetch_oa", None)), "固定 OA-only 入口尚未实现"
    return module


@pytest.mark.parametrize("identifier", ["1706.03762", "https://doi.org/10.1000/example"])
def test_oa_sources_receive_no_user_config_and_publish_valid_pdf(tmp_path, monkeypatch, identifier):
    calls = []

    def download(value, output, config):
        calls.append((value, config))
        output.write_bytes(b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n")
        return {"success": True, "file": str(output), "source": "OA"}

    wrapper = load_wrapper(monkeypatch, download)
    result = wrapper._fetch_oa(identifier, tmp_path)
    assert result["status"] == "success"
    assert Path(result["paper"]["pdf_path"]).read_bytes().startswith(b"%PDF-")
    assert len(calls) == 1
    assert calls[0][1]["download_strategy"] == "oa_only"
    assert not any(key in calls[0][1] for key in ("carsi_enabled", "cookies", "instsci_school", "elsevier_api_key"))


@pytest.mark.parametrize("contents", [None, b"<html>login challenge</html>", b"%PDF-1.4 truncated"])
def test_missing_or_fake_pdf_stays_manual_without_browser(tmp_path, monkeypatch, contents):
    def download(value, output, config):
        if contents is None:
            return None
        output.write_bytes(contents)
        return {"success": True, "file": str(output)}

    result = load_wrapper(monkeypatch, download)._fetch_oa("10.1000/example", tmp_path)
    assert result["status"] == "manual_required"
    assert result["next_action"]["kind"] == "local_pdf"
    assert "paper" not in result


def test_source_cannot_publish_pdf_outside_request_directory(tmp_path, monkeypatch):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n")

    def download(value, output, config):
        return {"success": True, "file": str(outside)}

    destination = tmp_path / "request"
    result = load_wrapper(monkeypatch, download)._fetch_oa("10.1000/example", destination)
    assert result["status"] == "manual_required"
    assert outside.is_file()


def test_existing_output_is_read_back_before_success(tmp_path, monkeypatch):
    contents = b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n"
    target = tmp_path / (hashlib.sha256(contents).hexdigest() + ".pdf")
    target.write_bytes(b"existing user file")

    def download(value, output, config):
        output.write_bytes(contents)
        return {"success": True, "file": str(output)}

    result = load_wrapper(monkeypatch, download)._fetch_oa("10.1000/example", tmp_path)
    assert result["status"] == "manual_required"
    assert target.read_bytes() == b"existing user file"


@pytest.mark.parametrize("changes", [{"legal_only": False}, {"institution": True}])
def test_provider_input_cannot_enable_institution_mode(tmp_path, monkeypatch, capsys, changes):
    def download(*args):
        pytest.fail("invalid request must not fetch")

    wrapper = load_wrapper(monkeypatch, download)
    payload = {"identifier": "10.1000/example", "destination": str(tmp_path / "result.pdf"),
               "legal_only": True, **changes}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert wrapper._provider_mode() == 4
    assert json.loads(capsys.readouterr().out)["status"] == "manual_required"
    assert not (tmp_path / "result.pdf").exists()


def test_source_loading_skips_package_initializers(tmp_path, monkeypatch):
    monkeypatch.setenv("UNPAYWALL_EMAIL", "fixture@example.org")
    package = tmp_path / "scansci_pdf"
    (package / "sources").mkdir(parents=True)
    marker = tmp_path / "forbidden-initializer.txt"
    initializer = f"from pathlib import Path\nPath({str(marker)!r}).write_text('side effect')\nraise RuntimeError('must not initialize registry')\n"
    (package / "__init__.py").write_text(initializer, encoding="utf-8")
    (package / "sources" / "__init__.py").write_text(initializer, encoding="utf-8")
    (package / "identifiers.py").write_text("def normalize_arxiv_id(value): return None\n", encoding="utf-8")
    (package / "sources" / "arxiv.py").write_text("def try_arxiv(*args): return None\n", encoding="utf-8")
    (package / "sources" / "unpaywall.py").write_text("def try_unpaywall(*args): return None\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    for name in tuple(sys.modules):
        if name == "scansci_pdf" or name.startswith("scansci_pdf."):
            monkeypatch.delitem(sys.modules, name)
    path = Path(__file__).resolve().parents[2] / "scripts" / "scansci_wrap.py"
    spec = importlib.util.spec_from_file_location("scansci_oa_clean", path)
    wrapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wrapper)
    try:
        result = wrapper._fetch_oa("10.1000/example", tmp_path / "output")
    except RuntimeError:
        result = None
    finally:
        for name in tuple(sys.modules):
            if name == "scansci_pdf" or name.startswith("scansci_pdf."):
                monkeypatch.delitem(sys.modules, name)
    assert not marker.exists(), "OA import must not initialize ScanSci or its source registry"
    assert result["status"] == "manual_required"


@pytest.mark.parametrize("open_access,availability,expected", [("Y", "OA", "success"), ("N", "OA", "manual_required"), ("Y", "S", "manual_required")])
def test_europe_pmc_only_downloads_explicit_open_access(tmp_path, monkeypatch, open_access, availability, expected):
    wrapper = load_wrapper(monkeypatch, lambda *args: pytest.fail("Unpaywall needs configured email"))
    monkeypatch.delenv("UNPAYWALL_EMAIL")
    network = types.ModuleType("scansci_pdf.network")
    network.fetch_json = lambda url, config: {"resultList": {"result": [{
        "isOpenAccess": open_access, "fullTextUrlList": {"fullTextUrl": [{
            "availabilityCode": availability, "documentStyle": "pdf", "url": "https://europepmc.org/articles/PMC123?pdf=render"
        }]}
    }]}}
    pdf_utils = types.ModuleType("scansci_pdf.pdf_utils")
    calls = []

    def download(url, output, config, source, **kwargs):
        assert kwargs.get("require_pdf_like_url") is False
        calls.append(url)
        output.write_bytes(b"%PDF-1.4\n" + b" " * 1100 + b"\n%%EOF\n")
        return {"success": True, "file": str(output)}

    pdf_utils.download_pdf = download
    monkeypatch.setitem(sys.modules, network.__name__, network)
    monkeypatch.setitem(sys.modules, pdf_utils.__name__, pdf_utils)
    result = wrapper._fetch_oa("10.1000/example", tmp_path)
    assert result["status"] == expected
    assert len(calls) == (1 if expected == "success" else 0)
