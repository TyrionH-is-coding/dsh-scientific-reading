"""scansci-pdf 驱动垫片（dsh-scientific-reading 插件自带）。

修复 scansci-pdf 1.9.0 的两个问题（仅在本插件调用路径生效，不动安装）：
1. 未配置机构时，fetch 的 Step 7 会无条件进 auth.login()，用空 instsci_base_url
   打开浏览器并崩溃（Page.goto 空 URL），导致即使论文已下载也无 JSON 输出。
   → 未配置机构时让 WebVPNAuth.login 快速返回 False。
2. arXiv 源 success() 返回 key 是 "file"，而 fetcher 读 result["path"]，
   导致 PDF 下了盘却永远不被认领（open_access 恒为 partial）。
   → 给返回补上 "path" 键。
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

# 强制 UTF-8 输出：中文 Windows 控制台默认 GBK，打印 JSON 会 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from scansci_pdf import auth as auth_mod
import scansci_pdf.sources.arxiv as arxiv_mod

# ── 修复 1：未配置机构时不弹浏览器 ────────────────────────────────
_orig_login = auth_mod.WebVPNAuth.login


def _safe_login(self, force: bool = False) -> bool:
    cfg = self.config or {}
    institution_configured = bool(
        cfg.get('vpnsci_enabled')
        or cfg.get('instsci_base_url')
        or cfg.get('carsi_enabled')
        or cfg.get('ezproxy_enabled')
    )
    if not institution_configured:
        return False  # 未配置机构：快速失败，不弹浏览器
    return _orig_login(self, force)


auth_mod.WebVPNAuth.login = _safe_login

# ── 修复 2：arXiv 成功返回补 "path" 键 ───────────────────────────
_orig_download = arxiv_mod.download_arxiv_pdf


def _patched_download(url, output_path, config):
    result = _orig_download(url, output_path, config)
    if result and 'file' in result and 'path' not in result:
        result['path'] = result['file']
    return result


arxiv_mod.download_arxiv_pdf = _patched_download

from scansci_pdf.main import app


def _extract_json(text: str):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _provider_mode() -> int:
    try:
        payload = json.load(sys.stdin)
        if set(payload) != {"identifier", "destination", "legal_only"}:
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
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                app(
                    args=["fetch", identifier, "--output", temporary, "--format", "json"],
                    standalone_mode=False,
                )
            noise = capture.getvalue()
            result = _extract_json(noise)
            paper = result.get("paper") if isinstance(result, dict) else None
            source = Path(str(paper.get("pdf_path", ""))) if isinstance(paper, dict) else None
            if result is None or result.get("status") != "success" or source is None or not source.is_file() or not source.resolve().is_relative_to(Path(temporary).resolve()):
                raise ValueError("scansci_fetch_failed")
            shutil.copyfile(source, destination)
            if noise.strip():
                print(noise, file=sys.stderr, end="" if noise.endswith("\n") else "\n")
        print(json.dumps({"status": "success", "path": str(destination.resolve())}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 4


if __name__ == "__main__":
    if len(sys.argv) == 1:
        raise SystemExit(_provider_mode())
    app()
