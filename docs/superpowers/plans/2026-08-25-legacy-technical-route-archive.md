# 旧技术路线文档归档 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不删除历史证据的前提下，把两个仓库的旧 Zotero/九节浅读技术路线移入归档，并让所有稳定文档入口准确描述当前两阶段/三阶段实现。

**Architecture:** 插件仓库保存跨仓库设计和当前产品入口，Python 引擎仓库保存领域实现与 PDF provider 合同。旧文件按原仓库、原 plans/specs 层级移动到 `docs/archive/`，内容不改写；原来的稳定入口路径使用当前实现重写，并通过关键词、路径和 Markdown 链接门禁验证。

**Tech Stack:** Markdown、Git、PowerShell、Python 3.11 标准库链接检查。

---

## Task 1：建立隔离工作树并记录失败基线

**Files:**

- Read: `D:\Vibe Coding\dsh-scientific-reading\docs\superpowers\specs\2026-08-25-legacy-technical-route-archive-design.md`
- Read: `D:\Vibe Coding\dsh-scientific-reading\README.md`
- Read: `D:\Vibe Coding\Scientific-Reading-for-Newbies\README.md`

- [ ] **Step 1: 检查 main 和用户改动**

```powershell
git -C "D:\Vibe Coding\dsh-scientific-reading" status --short
git -C "D:\Vibe Coding\Scientific-Reading-for-Newbies" status --short
```

预期：插件只允许已有用户文件 `?? docs/survey.html`；引擎 clean。若出现其他改动，保留并避开，不使用 reset 或 checkout 清除。

- [ ] **Step 2: 创建本任务 worktree**

```powershell
git -C "D:\Vibe Coding\dsh-scientific-reading" worktree add ".worktrees\archive-legacy-docs" -b docs/archive-legacy-route main
git -C "D:\Vibe Coding\Scientific-Reading-for-Newbies" worktree add ".worktrees\archive-legacy-docs" -b docs/archive-legacy-route main
```

预期：两个 worktree 分别位于各仓库 `.worktrees/archive-legacy-docs`，不接触 reader v2.1 的现有独立 worktree。

- [ ] **Step 3: 运行旧路线失败基线**

在插件 worktree 的当前入口中运行：

```powershell
rg -n "Zotero Desktop|九节式|Phase 0|下一步|reading/full/output/reader_full.html|zotero-migrate|sr_zotero_migrate" `
  README.md docs/design.md docs/features.md docs/roadmap.md docs/handoff-dsh-native.md
```

在引擎 worktree 的当前入口中运行：

```powershell
rg -n "默认仍优先复用 Zotero|回挂 Zotero|Zotero 读回闭环" README.md docs/scansci-pdf-integration.md
```

预期：两条命令均有命中，证明当前入口仍混有旧路线；该失败基线随后由 Task 2/3 消除。

## Task 2：归档插件旧路线并重写稳定入口

**Files:**

- Create: `D:\Vibe Coding\dsh-scientific-reading\.worktrees\archive-legacy-docs\docs\archive\README.md`
- Create: `D:\Vibe Coding\dsh-scientific-reading\.worktrees\archive-legacy-docs\docs\archive\pre-two-stage-plugin\README.md`
- Create: `D:\Vibe Coding\dsh-scientific-reading\.worktrees\archive-legacy-docs\docs\README.md`
- Replace: `docs/design.md`
- Replace: `docs/features.md`
- Replace: `docs/roadmap.md`
- Replace: `docs/handoff-dsh-native.md`
- Move: `docs/borrowed-ideas.md`
- Move: `docs/superpowers/plans/2026-08-21-*.md`
- Move: `docs/superpowers/plans/2026-08-22-*.md`
- Move: `docs/superpowers/plans/2026-08-23-live-qa-repair.md`
- Move: `docs/superpowers/specs/2026-08-21-*.md`
- Move: `docs/superpowers/specs/2026-08-22-*.md`
- Move: `docs/superpowers/specs/2026-08-23-live-qa-repair-design.md`

- [ ] **Step 1: 移动旧文件且保留原内容**

建立 `docs/archive/pre-two-stage-plugin/{entry-snapshots,plans,specs}`。把四个旧入口移动到 `entry-snapshots/`，把借鉴清单移到归档根，把列出的 plans/specs 移到对应目录。不得移动：

```text
2026-08-23-two-stage-literature-workflow-*
2026-08-24-reader-html-v2-1*
2026-08-24-reader-html-periodical-first*
2026-08-24-reader-periodical-first-demo.md
2026-08-25-legacy-technical-route-archive-design.md
2026-08-25-legacy-technical-route-archive.md
```

使用 `git diff --summary` 确认 Git 识别为 rename；归档快照正文不做批量替换。

- [ ] **Step 2: 写归档说明和当前文档索引**

`docs/archive/README.md` 必须包含：归档日期 2026-08-25、归档内容不定义当前行为、当前入口是根 README 与 `docs/README.md`、可用 Git 历史追溯原路径。

`docs/README.md` 只链接：根 README、design、features、roadmap、handoff、两阶段/三阶段总索引、reader v2.1 和期刊正文优先设计、archive README。

- [ ] **Step 3: 重写 `docs/design.md`**

正文使用以下固定架构：

```text
DSH 文献页/工具
  -> TypeScript 插件（参数、路由、UI、合法 PDF provider）
  -> Python 引擎（SQLite、任务、PDF 校验、MinerU、翻译、reader、XLSX/飞书派生）
  -> 仓库外 data root
```

明确：SQLite 是唯一事实来源；快速入库不等待 PDF/MinerU；全文精读使用持久 parent job；正式 reader 位于 `papers/<paper_id>/generations/<sha16>/reading/reader.html`；无 Zotero 运行入口；旧字段和旧资产只读兼容。

- [ ] **Step 4: 重写 `docs/features.md`**

只保留四节：快速入库、文献导航、按需精读与资产、飞书/XLSX 派生。每项只用“已完成”或“当前限制”，不使用旧 Phase 编号，不宣传九节式笔记、关键图 AI 判断、批量机构下载或双向同步。

- [ ] **Step 5: 重写 `docs/roadmap.md`**

写成完成基线与后续独立范围：

```text
已完成：本地主库与 Abstract 浅读；精读 parent job 与 generation 资产；文献导航/批量/迁移审计；隔离与 persistent Profile 验收。
后续独立范围：期刊正文优先 builder 迁移；获明确授权后的首次真实飞书写入验收。
明确不做：Zotero 运行链恢复、九节浅读恢复、AI 关键图挑选、批量机构下载、飞书双向同步。
```

- [ ] **Step 6: 重写 `docs/handoff-dsh-native.md`**

保留当前职责、数据根、构建命令、测试门禁、真实 Bundle 三层验证、飞书/机构认证边界和本地合并规则。删除固定 commit、工具数量、测试数量、表格记录数、旧论文状态和旧路由数量。

- [ ] **Step 7: 运行插件文档门禁并提交**

```powershell
rg -n "Zotero Desktop|九节式|Phase 0|下一步|reading/full/output/reader_full.html|zotero-migrate|sr_zotero_migrate" `
  README.md docs/design.md docs/features.md docs/roadmap.md docs/handoff-dsh-native.md
git diff --check
git add -- docs
git commit -m "文档：归档插件旧技术路线"
```

预期：`rg` 无命中并返回 1；`git diff --check` 无输出；提交只包含文档。

## Task 3：归档引擎旧路线并更新 ScanSci 合同

**Files:**

- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\.worktrees\archive-legacy-docs\docs\archive\README.md`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\.worktrees\archive-legacy-docs\docs\archive\legacy-zotero-workflow\README.md`
- Create: `D:\Vibe Coding\Scientific-Reading-for-Newbies\.worktrees\archive-legacy-docs\docs\README.md`
- Replace: `docs/scansci-pdf-integration.md`
- Move: `docs/superpowers/plans/*.md`
- Move: `docs/superpowers/specs/*.md`

- [ ] **Step 1: 移动引擎旧阶段文档**

把当前 `docs/superpowers/plans/*.md` 移到 `docs/archive/legacy-zotero-workflow/plans/`，把 `docs/superpowers/specs/*.md` 移到 `docs/archive/legacy-zotero-workflow/specs/`。把旧 `docs/scansci-pdf-integration.md` 移到 `docs/archive/legacy-zotero-workflow/scansci-pdf-integration-zotero-era.md`，不改写归档正文。

- [ ] **Step 2: 写引擎归档说明和索引**

`docs/README.md` 链接根 README、当前 ScanSci 集成、`reader/README.md` 和 archive README。归档说明必须指出这些文件记录 2026-07/08 的 Zotero 主库与九节浅读路线，不得作为当前 CLI 或 worker 指令。

- [ ] **Step 3: 重写当前 ScanSci 集成文档**

当前链路固定为：

```text
精读 parent job 请求 PDF
  -> 插件受信任 provider 调用 ScanSci legal_only
  -> 返回逐篇候选文件
  -> 引擎校验 PDF 身份、大小和 SHA
  -> 写入 generation/source.pdf 与 SQLite attachment
  -> parent job 从已完成阶段继续
```

明确 ScanSci 不是引擎必选依赖；失败转 `needs_user`；机构浏览器必须逐篇显式授权；不读取凭据/Cookie；不调用 Zotero；不把 provider 成功直接等同于 `pdf_ready`。

- [ ] **Step 4: 运行引擎文档门禁并提交**

```powershell
rg -n "默认仍优先复用 Zotero|回挂 Zotero|Zotero 读回闭环|reading/full/output/reader_full.html" `
  README.md docs/README.md docs/scansci-pdf-integration.md reader/README.md
git diff --check
git add -- docs
git commit -m "文档：归档引擎旧技术路线"
```

预期：`rg` 无命中并返回 1；`git diff --check` 无输出；提交只包含文档。

## Task 4：跨仓库链接与范围验证

**Files:**

- Verify: 两个 worktree 中的全部 tracked Markdown

- [ ] **Step 1: 检查 Markdown 相对链接**

在每个 worktree 根目录运行以下 Python 标准库脚本；它忽略 HTTP、锚点和绝对路径，只检查仓库内相对文件链接：

```powershell
@'
from pathlib import Path
import re, sys
root = Path.cwd()
broken = []
for md in root.rglob("*.md"):
    if any(part in {".git", ".worktrees", "node_modules", ".venv"} for part in md.parts):
        continue
    text = md.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = target.strip().strip("<>").split("#", 1)[0]
        if not target or "://" in target or target.startswith(("#", "/", "C:", "D:")):
            continue
        candidate = (md.parent / target).resolve()
        if not candidate.exists():
            broken.append(f"{md.relative_to(root)} -> {target}")
if broken:
    print("\n".join(broken))
    sys.exit(1)
print("markdown_links_ok")
'@ | python -
```

预期：两个仓库都输出 `markdown_links_ok`。

- [ ] **Step 2: 检查当前/归档分界**

```powershell
rg -l "Zotero Desktop|九节式|zotero-migrate|sr_zotero_migrate" docs `
  | Where-Object { $_ -notmatch "docs[\\/]archive" -and $_ -notmatch "two-stage-literature-workflow" }
```

预期：插件最多命中说明“明确不恢复旧路线”的当前设计/roadmap；引擎当前入口不命中。逐个解释任何剩余项，不为追求零命中而改写已完成的两阶段迁移证据。

- [ ] **Step 3: 检查只改文档**

```powershell
git diff main --name-only | Where-Object { $_ -notmatch '^(README\.md|docs/|reader/README\.md)' }
git diff main --check
```

预期：第一条无输出，第二条无输出。

## Task 5：本地合并 main、重验并清理

**Files:**

- Modify: 两仓库 `main` 历史
- Preserve: `D:\Vibe Coding\dsh-scientific-reading\docs\survey.html`
- Preserve: reader v2.1 独立 worktree/branch

- [ ] **Step 1: 先合并引擎，再合并插件**

在各自 main 仓库使用 `--no-ff` 合并 `docs/archive-legacy-route`，中文 merge commit；不 stash、不删除用户文件。

- [ ] **Step 2: 在 main 重跑文档门禁**

重复 Task 2 Step 7、Task 3 Step 4 和 Task 4 的链接检查。确认两仓库 `git diff --check` 通过；插件 `git status --short` 仍只允许 `?? docs/survey.html`。

- [ ] **Step 3: 清理本任务工作树与分支**

```powershell
git -C "D:\Vibe Coding\Scientific-Reading-for-Newbies" worktree remove ".worktrees\archive-legacy-docs"
git -C "D:\Vibe Coding\Scientific-Reading-for-Newbies" branch -d docs/archive-legacy-route
git -C "D:\Vibe Coding\dsh-scientific-reading" worktree remove ".worktrees\archive-legacy-docs"
git -C "D:\Vibe Coding\dsh-scientific-reading" branch -d docs/archive-legacy-route
```

预期：本任务 worktree/branch 消失；reader v2.1 工作树仍存在；3080、飞书、机构认证和 GitHub 均未操作。
