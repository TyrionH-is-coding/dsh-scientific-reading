"""scansci-pdf 驱动垫片（dsh-scientific-reading 插件自带）。

修复 scansci-pdf 1.9.0 的两个问题（仅在本插件调用路径生效，不动安装）：
1. 未配置机构时，fetch 的 Step 7 会无条件进 auth.login()，用空 instsci_base_url
   打开浏览器并崩溃（Page.goto 空 URL），导致即使论文已下载也无 JSON 输出。
   → 未配置机构时让 WebVPNAuth.login 快速返回 False。
2. arXiv 源 success() 返回 key 是 "file"，而 fetcher 读 result["path"]，
   导致 PDF 下了盘却永远不被认领（open_access 恒为 partial）。
   → 给返回补上 "path" 键。
"""

import sys

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

app()
