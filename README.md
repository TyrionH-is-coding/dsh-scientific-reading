# @dsh-external/dsh-scientific-reading

文献工作流插件（Phase 0：下载段已可用）。把 Scientific-Reading-for-Newbies 的
完整文献流水线搬进 DSH：下载 → 解析 → 入库 → 笔记。

## 当前状态（Phase 0）

已注入 DSH 并热重载验证，工具：

| 工具 | 作用 |
|---|---|
| `sr_setup` | 检查/安装 scansci-pdf + 合法来源配置（默认关 Sci-Hub） |
| `sr_scansci_status` | 下载器健康 + 学校/输出目录/合法开关总览 |
| `sr_scansci_fetch` | DOI/URL → PDF 落盘 + 元数据 JSON |
| `sr_scansci_login` | 机构登录（CARSI/WebVPN/Cookie，浏览器弹出，密码不经过插件） |
| `sr_scansci_set_school` | 设置学校 |

## 构建与注入

```powershell
# 编译（typescript 在隔离目录 D:\Vibe Coding\_tsc）
node "D:\Vibe Coding\_tsc\node_modules\typescript\lib\tsc.js" -p tsconfig.json
# 注入/重载（DSH dev 工具）
dev_build_plugin / dev_inject_plugin / dev_reload_package
```

## 垫片说明

`scripts/scansci_wrap.py` 修复 scansci-pdf 1.9.0 的三个问题（仅本插件调用路径生效）：

1. 未配置机构时跳过浏览器登录（防空 URL 崩溃）；
2. arXiv 成功返回补 `path` 键（原返回 `file`，fetcher 读 `path` 导致 PDF 永不认领）；
3. 强制 UTF-8 输出（中文 Windows 控制台 GBK 报错）。

## 路线图

见 `docs/roadmap.md`：Phase 0 下载段 ✅ → Phase 1 本地文献库（SQLite，替代 Zotero）
→ Phase 2 【文献】标签页（conversation.view）→ Phase 3 飞书/精读/迁移。
