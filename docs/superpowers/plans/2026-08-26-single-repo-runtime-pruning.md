# 单仓库运行时瘦身 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把当前 DSH 插件与必要 Python 引擎合并为一个无旧技术路线残余、可独立安装和验收的仓库。

**Architecture:** 用白名单复制而非完整迁移旧引擎；插件只调用仓内 wheel。MinerU API 是唯一解析边界，摘要浅读与全文精读是仅有阅读流程，用户旧资产保持原位但不携带旧执行代码。

**Tech Stack:** TypeScript/Node.js、Python 3.11+、pytest、MinerU HTTP API、SQLite、Pillow、npm pack。

---

### Task 1: 锁定白名单与可复现构建

**Files:**
- Create: `tests/current-runtime-boundary.mjs`
- Modify: `package.json`
- Modify: `scripts/build.sh`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: 写失败的边界测试**

测试递归扫描受控运行时文件，拒绝 `Scientific-Reading-for-Newbies`、`PyMuPDF`、`fitz`、`zotero`、`mineru_runner`、`local-cli`、`sr_parse`、`sr_quick_read`、`sr_full_read`，并断言公开工具等于设计白名单。

- [ ] **Step 2: 运行测试并确认因现有残余失败**

Run: `node tests/current-runtime-boundary.mjs`
Expected: FAIL，列出当前旧工具和外部仓库路径。

- [ ] **Step 3: 修正 Windows 构建入口与 npm 脚本**

把 `build` 改为跨平台 Node 构建入口，增加 `test`、`test:python`、`test:integration` 和 `test:package`；CI 使用 `npm ci --legacy-peer-deps`，不依赖 WSL/bash。

- [ ] **Step 4: 运行构建与现有离线测试**

Run: `npm run build && npm run test:offline`
Expected: 构建成功；记录并修复仅由新构建入口暴露的问题。

- [ ] **Step 5: 中文提交**

Run: `git commit -m "构建：锁定当前运行时白名单"`

### Task 2: 迁入最小 Python 引擎

**Files:**
- Create: `engine/pyproject.toml`
- Create: `engine/src/scientific_reading/*.py`
- Create: `engine/reader/*`
- Create: `engine/tests/*`
- Create: `LICENSE`
- Create: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: 写 wheel 内容失败测试**

断言 wheel 不含 `fast_parser.py`、`quick_read_*`、`zotero_*`、`mineru_runner.py`、`migration_audit.py`，且元数据为 BSD-3-Clause、版权人为 `TyrionH-is-coding`。

- [ ] **Step 2: 运行并确认 wheel 尚不存在**

Run: `python -m pytest tests/test_engine_package_boundary.py -q`
Expected: FAIL，原因是 `engine/` 或 wheel 不存在。

- [ ] **Step 3: 按导入闭包迁入白名单模块**

从固定基线 `275efea` 复制当前主链所需模块；将共享身份判断移入 `identifiers.py`，不通过保留 `fast_parser.py` 解决导入；删除所有旧 handler 和 CLI 分支。

- [ ] **Step 4: 建立最小 CLI**

CLI 仅暴露插件当前适配器实际调用的 library、folder、classification、abstract、full-read、artifact/export、feishu-resync、job-status 命令。

- [ ] **Step 5: 构建并检查 wheel**

Run: `python -m build engine --wheel && python -m pytest tests/test_engine_package_boundary.py -q`
Expected: PASS，wheel 内无禁用模块或字符串。

- [ ] **Step 6: 中文提交**

Run: `git commit -m "引擎：迁入当前主链最小运行时"`

### Task 3: MinerU API 单一路线与 PDF 轻预检

**Files:**
- Modify: `engine/src/scientific_reading/mineru_service.py`
- Modify: `engine/src/scientific_reading/pdf_validation.py`
- Modify: `engine/src/scientific_reading/export_service.py`
- Test: `engine/tests/test_mineru_api_only.py`
- Test: `engine/tests/test_pdf_preflight.py`

- [ ] **Step 1: 写失败测试**

覆盖：无 API 凭证时报 `mineru_credentials_required`；服务不接受 executable/runner；预检只读签名/大小/SHA；导出只复制 MinerU 资产并用 Pillow 验证。

- [ ] **Step 2: 运行并确认失败**

Run: `python -m pytest engine/tests/test_mineru_api_only.py engine/tests/test_pdf_preflight.py -q`
Expected: FAIL，现有服务仍包含 local CLI 或 PyMuPDF 行为。

- [ ] **Step 3: 实现最小 API-only 边界**

删除 runner/executable/cache identity 分支；使用标准库读取 PDF 头、大小和 SHA-256；移除 bbox PDF 裁图，只接受 manifest 中已校验的 MinerU 相对资产路径。

- [ ] **Step 4: 运行定向与引擎全量测试**

Run: `python -m pytest engine/tests/test_mineru_api_only.py engine/tests/test_pdf_preflight.py -q && python -m pytest engine/tests -q`
Expected: 全部 PASS。

- [ ] **Step 5: 中文提交**

Run: `git commit -m "解析：统一使用MinerU官方API"`

### Task 4: 删除插件旧工具和旧阅读入口

**Files:**
- Modify: `src/library_tools.ts`
- Modify: `src/cli.ts`
- Modify: `src/routes.ts`
- Modify: `src/papers.ts`
- Modify: `client/client.js`
- Modify: `tests/harness.mjs`
- Modify: `tests/client-actions.mjs`

- [ ] **Step 1: 扩展失败测试**

断言工具清单精确相等；路由不读取 `reading/quick_read.md`；paper id 不再接受 `zotero_`；CLI 适配器不含旧命令。

- [ ] **Step 2: 运行并确认失败**

Run: `node tests/current-runtime-boundary.mjs && node tests/harness.mjs`
Expected: FAIL，指出旧工具和旧路由。

- [ ] **Step 3: 删除旧注册和适配器**

删除 `sr_init`、`sr_library_check`、`sr_library_ensure`、`sr_pdf_attach`、`sr_library_search`、`sr_parse`、`sr_quick_read`、`sr_full_read`、`sr_feishu_preview`、`sr_feishu_sync` 及其无调用适配函数；保留白名单工具。

- [ ] **Step 4: 删除旧 UI/路由兼容**

去掉“历史浅读”入口和根目录 quick_read 读取；reader 只解析 active generation 的 `reading/reader.html`。

- [ ] **Step 5: 构建并运行插件测试**

Run: `npm run build && npm run test:offline`
Expected: 全部 PASS。

- [ ] **Step 6: 中文提交**

Run: `git commit -m "插件：移除旧工具与历史阅读入口"`

### Task 5: 单仓库安装、打包与路径修复

**Files:**
- Modify: `src/setup.ts`
- Modify: `scripts/verify-profile-runtime.mjs`
- Modify: `scripts/verify_navigation_runtime.mjs`
- Modify: `scripts/verify_full_read_pipeline.py`
- Modify: `tests/foundation-integration.mjs`
- Modify: `tests/full-read-integration.mjs`
- Modify: `tests/package-contents.mjs`
- Create: `MIGRATION.md`

- [ ] **Step 1: 写失败测试**

断言所有路径从仓库内 `engine/` 或 tarball 内 `dist/python/*.whl` 解析；禁止 `SR_ENGINE_ROOT` 和相邻仓库探测；`sr_setup` 从内置 wheel 建 venv。

- [ ] **Step 2: 运行并确认失败**

Run: `node tests/package-contents.mjs && node tests/current-runtime-boundary.mjs`
Expected: FAIL，指出跨仓库路径或 wheel 缺失。

- [ ] **Step 3: 实现仓内 wheel 安装**

构建阶段生成 wheel 并纳入 npm files；setup 在 `%USERPROFILE%/scientific-reading-data/.venv` 创建环境并安装该 wheel；仅显式 `enginePython` 覆盖默认解释器。

- [ ] **Step 4: 改写集成测试路径**

测试使用仓内 engine 与临时 data root，不访问外部 checkout、真实飞书或机构认证。

- [ ] **Step 5: 验证 tarball**

Run: `npm pack --dry-run && npm run test:package`
Expected: tarball 含 wheel、LICENSE、THIRD_PARTY_NOTICES、MIGRATION；不含源码缓存或历史文档。

- [ ] **Step 6: 中文提交**

Run: `git commit -m "安装：实现单仓库内置引擎"`

### Task 6: 端到端验收与合并

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/monorepo-smoke.mjs`

- [ ] **Step 1: 写 fake 端到端测试**

用临时 data root、虚构工科 metadata、本地最小 PDF、fake MinerU client 和 fake 飞书 client，验证 ingest → abstract → full-read → reader → export → resync → job-status。

- [ ] **Step 2: 运行并确认缺失链路失败**

Run: `npm run test:integration`
Expected: FAIL，直到单仓库安装和当前主链全部接通。

- [ ] **Step 3: 完成最小接线并更新中文 README**

README 只写单仓库安装、MinerU API、ScanSci/手动 PDF、当前工具和故障诊断；删除双仓库步骤。

- [ ] **Step 4: 全量验证**

Run: `npm run build && npm test`
Expected: Python、Node、集成、打包全部 PASS；环境中清空 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`，不发真实写请求。

- [ ] **Step 5: 残余与工作树验证**

Run: `node tests/current-runtime-boundary.mjs && git diff --check && git status --short`
Expected: 无禁用残余、无 whitespace 错误，仅计划内变更。

- [ ] **Step 6: 中文提交并本地合并**

Run: `git commit -m "交付：完成单仓库文献阅读工作流"`

合并到 main 后再次运行 `npm run build && npm test`，再清理 feature worktree；本轮不删除旧引擎仓库，不进行真实飞书写入。
