# V1 设置页、解析后端与文献页收口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付首次设置体检、安全 MinerU Key、本机/API 双解析后端、批量 PDF 下载、紧凑文献页和 Excel 白名单维护组成的 V1 个人文献库。

**Architecture:** TypeScript 插件只负责 DSH 页面、同源 HTTP 边界和命令编排；内置 Python 引擎负责 SQLite、DPAPI、MinerU provider、批量任务和 Excel。所有解析后端输出先进入隔离 staging，再经过现有 `MineruNormalizer` 和资产校验发布；SQLite 继续作为系统事实来源。

**Tech Stack:** TypeScript、Cordis/DSH slots、Node.js HTTP、Python 3.11、SQLite、openpyxl、Windows DPAPI、系统 Chrome、MinerU CLI/API、Node test harness、pytest。

---

## 文件结构

- `engine/src/scientific_reading/environment_status.py`：首次展示状态、静态/手动探测快照和脱敏诊断。
- `engine/src/scientific_reading/secret_store.py`：Windows DPAPI Key 保存、读取、删除与来源解析。
- `engine/src/scientific_reading/mineru_provider.py`：统一 provider 协议、选择策略和错误模型。
- `engine/src/scientific_reading/mineru_local.py`：本机 MinerU 探测与隐藏子进程解析。
- `engine/src/scientific_reading/mineru_service.py`：复用现有规范化、缓存和发布逻辑，消费统一 provider。
- `engine/src/scientific_reading/xlsx_snapshot.py`：美观工作簿、用户字段回写和按 `paper_id` 定位。
- `src/status_routes.ts`：设置页状态、手动检测、Key 写入/删除和 Excel 定位 HTTP 边界。
- `src/download_batch.ts`：单篇/批量缺失 PDF 编排和父汇总。
- `client/client.js`：两个原生页面、首次展示、紧凑列表和批量栏；`lib/client.js` 继续由构建生成。

### Task 1: 建立隔离执行基线和当前合同

**Files:**
- Read: `docs/superpowers/specs/2026-08-27-v1-settings-library-ui-design.md`
- Create: `.worktrees/v1-release`
- Test: `engine/tests/`、`tests/`

- [ ] **Step 1: 创建隔离 worktree**

Run:

```powershell
git worktree add ".worktrees\v1-release" -b "feature/v1-release" main
```

Expected: 新 worktree 指向当前 `main`；根目录的 `docs/coding-backlog.md` 和 `docs/survey.html` 不进入 worktree 提交。

- [ ] **Step 2: 安装并验证基线**

Run:

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
```

Expected: 全部退出码为 0；记录实际测试数量，但不把数量写入长期合同。

- [ ] **Step 3: 提交基线记录文件**

在计划末尾的执行记录中写入基线命令与结果，然后：

```powershell
git add docs/superpowers/plans/2026-08-27-v1-settings-library-ui.md
git commit -m "计划：记录首版开发基线"
```

### Task 2: 移除飞书现行运行入口

**Files:**
- Modify: `engine/src/scientific_reading/library_schema.py`
- Modify: `engine/src/scientific_reading/xlsx_snapshot.py`
- Modify: `engine/src/scientific_reading/__main__.py`
- Modify: `engine/src/scientific_reading/worker.py`
- Delete: `engine/src/scientific_reading/feishu_builder.py`
- Delete: `engine/src/scientific_reading/feishu_http.py`
- Delete: `engine/src/scientific_reading/feishu_models.py`
- Delete: `engine/src/scientific_reading/feishu_service.py`
- Modify: `src/config.ts`, `src/cli.ts`, `src/library_tools.ts`, `src/routes.ts`
- Delete: `tests/feishu-env-only.mjs`, `engine/tests/test_feishu_http.py`
- Test: `tests/current-runtime-boundary.mjs`, `tests/harness.mjs`, `engine/tests/test_library_navigation.py`

- [ ] **Step 1: 写飞书退场失败测试**

在 `tests/current-runtime-boundary.mjs` 断言当前工具与 schema 不再包含飞书：

```js
for (const retired of ['sr_feishu_resync', 'feishuConfig', 'feishu_record_url']) {
  assert.equal(JSON.stringify(runtimeContract).includes(retired), false, retired)
}
```

在 Python 导航测试断言 `feishu_*` 遗留列不再被读取或返回。为保护既有 SQLite，不为删除旧列重建用户数据库；旧列只作为不可见、不可写的迁移兼容保留。

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
node tests\current-runtime-boundary.mjs
python -m pytest engine\tests\test_library_navigation.py -q
```

Expected: 因现有飞书工具、配置和字段仍存在而失败。

- [ ] **Step 3: 最小删除现行入口**

将 `Config` 收敛为：

```ts
export interface Config {
  dataRoot: string
  python: string
  scansciExe: string
  school: string
  legalOnly: boolean
  outputDir: string
  loginType: string
  scansciPython: string
  enginePython: string
}
```

删除飞书 CLI、worker 分支、工具、路由字段和 XLSX 列。新旧数据库都不再读取或写入遗留列，不重建或破坏用户现有 SQLite。

- [ ] **Step 4: 运行退场测试和全量小门禁**

Run:

```powershell
python -m pytest engine\tests -q
npm.cmd run build:ci
npm.cmd run test:offline
```

Expected: 全部通过，`rg -n "sr_feishu|feishuConfig|FEISHU_APP" src client engine/src tests engine/tests` 无现行命中。

- [ ] **Step 5: 提交**

```powershell
git add engine src client tests package.json
git commit -m "清理：移除飞书现行运行链路"
```

### Task 3: 设置快照、首次展示与手动检测

**Files:**
- Create: `engine/src/scientific_reading/environment_status.py`
- Modify: `engine/src/scientific_reading/__main__.py`
- Create: `engine/tests/test_environment_status.py`
- Create: `src/status_routes.ts`
- Modify: `src/index.ts`
- Create: `tests/settings-status-routes.mjs`

- [ ] **Step 1: 写首次展示与缓存失败测试**

Python 测试使用临时 data root：

```python
service = EnvironmentStatusService(tmp_path)
assert service.snapshot()["onboarding"]["show_settings"] is True
service.mark_presented("v1")
assert service.snapshot()["onboarding"]["show_settings"] is False
assert network_spy.calls == []
```

Node 路由测试断言 GET 只返回快照，POST `/sr/api/settings/recheck` 才调用 probe。

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest engine\tests\test_environment_status.py -q
node tests\settings-status-routes.mjs
```

Expected: 模块和路由不存在。

- [ ] **Step 3: 实现状态模型**

`EnvironmentStatusService` 的公开返回固定为：

```python
{
    "contract_version": "environment-status-v1",
    "onboarding": {"show_settings": bool, "version": "v1"},
    "download": {"status": str, "checked_at": str | None},
    "institution": {"status": str, "school": str, "checked_at": str | None},
    "mineru": {"local": dict, "api": dict, "strategy": str},
    "library": {"status": str, "papers": int, "xlsx_pending": int},
}
```

静态 snapshot 不调用网络；`recheck(targets)` 只探测请求目标并原子写入 `<data-root>/status/environment-status-v1.json`。

- [ ] **Step 4: 实现同源路由与脱敏**

注册 GET snapshot、POST mark-presented、POST recheck。所有 POST 要求 JSON、同源 Origin 和 CSRF header；错误只返回稳定 code。

- [ ] **Step 5: 验证并提交**

```powershell
python -m pytest engine\tests\test_environment_status.py -q
node tests\settings-status-routes.mjs
npm.cmd run typecheck
git add engine/src/scientific_reading/environment_status.py engine/src/scientific_reading/__main__.py engine/tests/test_environment_status.py src/status_routes.ts src/index.ts tests/settings-status-routes.mjs
git commit -m "功能：加入首次设置与环境状态快照"
```

### Task 4: DPAPI MinerU Key 安全存储

**Files:**
- Create: `engine/src/scientific_reading/secret_store.py`
- Create: `engine/tests/test_secret_store.py`
- Modify: `engine/src/scientific_reading/mineru_api.py`
- Modify: `src/status_routes.ts`
- Replace: `tests/mineru-env-only.mjs` with `tests/mineru-secret-boundary.mjs`

- [ ] **Step 1: 写安全边界失败测试**

```python
store = MineruSecretStore(tmp_path, protector=fake_dpapi)
store.save("fictional-key")
assert b"fictional-key" not in store.path.read_bytes()
assert store.load() == "fictional-key"
store.delete()
assert store.load() is None
```

Node 测试扫描 Config、日志、HTTP 响应和 argv，断言不存在 Key；跨源和缺少 CSRF 的写入返回 403。

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest engine\tests\test_secret_store.py -q
node tests\mineru-secret-boundary.mjs
```

- [ ] **Step 3: 实现 DPAPI 和来源解析**

实现接口：

```python
class MineruSecretStore:
    def save(self, value: str) -> None: ...
    def load(self) -> str | None: ...
    def delete(self) -> None: ...

def resolve_mineru_token(data_root: Path) -> tuple[str | None, str]:
    stored = MineruSecretStore(data_root).load()
    return (stored, "secure_store") if stored else (os.getenv("MINERU_API_TOKEN"), "environment")
```

Windows 使用 `CryptProtectData`/`CryptUnprotectData` 当前用户作用域；非 Windows 只允许测试 protector 或环境变量，不写明文 fallback。

- [ ] **Step 4: 接入 Key 保存、替换、删除、验证路由**

请求体上限 16 KiB，只接受 `{ "api_key": "..." }`；响应只包含 `status`、`source`、`checked_at`。保存后前端不获得 Key 回显。

- [ ] **Step 5: 验证并提交**

```powershell
python -m pytest engine\tests\test_secret_store.py engine\tests\test_mineru_api.py -q
node tests\mineru-secret-boundary.mjs
npm.cmd run typecheck
git add engine src tests
git commit -m "安全：使用 DPAPI 保存 MinerU 密钥"
```

### Task 5: 本机/API MinerU provider

**Files:**
- Create: `engine/src/scientific_reading/mineru_provider.py`
- Create: `engine/src/scientific_reading/mineru_local.py`
- Create: `engine/tests/test_mineru_provider.py`
- Create: `engine/tests/test_mineru_local.py`
- Modify: `engine/src/scientific_reading/mineru_service.py`
- Modify: `engine/src/scientific_reading/mineru_artifacts.py`
- Modify: `engine/src/scientific_reading/reading_pipeline.py`
- Rename: `engine/tests/test_mineru_api_only.py` to `engine/tests/test_mineru_provider_contract.py`

- [ ] **Step 1: 写 provider 选择失败测试**

```python
assert choose_provider("auto", local=ready_local, api=ready_api).provider_id == "mineru-local-v1"
assert choose_provider("auto", local=missing_local, api=ready_api).provider_id == "mineru-api-v4"
with pytest.raises(MineruProviderError, match="mineru_local_unavailable"):
    choose_provider("local", local=missing_local, api=ready_api)
```

再断言任务选定 provider 后，local 失败不会调用 API spy。

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest engine\tests\test_mineru_provider.py engine\tests\test_mineru_local.py -q
```

- [ ] **Step 3: 实现统一协议与本机探测**

```python
class MineruProvider(Protocol):
    provider_id: str
    version: str
    def probe(self) -> MineruProbe: ...
    def parse(self, pdf: Path, staging: Path, method: str, heartbeat: Callable[[], None]) -> ProviderResult: ...
```

本机探测只接受支持版本、唯一 content list 和完整模型检查。使用参数数组启动隐藏子进程，不拼接 shell 字符串。

- [ ] **Step 4: 改造服务的 cache identity 与校验**

cache identity 加入 `provider_id`、provider 版本、方法、规范化版本和 PDF SHA。`MineruArtifactValidator` 接受已登记的 local/API provider，而不是硬编码 API；两者均调用同一个 `MineruNormalizer`。

- [ ] **Step 5: 验证并提交**

```powershell
python -m pytest engine\tests\test_mineru_provider.py engine\tests\test_mineru_local.py engine\tests\test_mineru_api.py engine\tests\test_mineru_normalizer.py -q
python -m pytest engine\tests -q
git add engine
git commit -m "功能：支持本机与 API 双 MinerU 后端"
```

### Task 6: Excel 美化、白名单回写与定位

**Files:**
- Modify: `engine/src/scientific_reading/library_schema.py`
- Modify: `engine/src/scientific_reading/xlsx_snapshot.py`
- Modify: `engine/tests/test_xlsx_snapshot.py`
- Modify: `engine/src/scientific_reading/__main__.py`
- Modify: `src/status_routes.ts`
- Create: `tests/excel-actions.mjs`

- [ ] **Step 1: 写 Excel 合同失败测试**

测试工作簿冻结首行、筛选、列宽、换行、用户列样式，并修改用户列后导入：

```python
sheet["个人思考2"] = "自己的判断"
sheet["个人理解程度2"] = "基本理解"
sheet["用户笔记2"] = "复习图 2"
service.import_user_fields()
assert load_user_fields(paper_id)["personal_thoughts"] == "自己的判断"
```

同时修改题名和 `paper_id`，断言题名不回写、身份异常行进入 conflict。

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest engine\tests\test_xlsx_snapshot.py -q
node tests\excel-actions.mjs
```

- [ ] **Step 3: 增加用户字段 schema 与导入**

items 新增 `personal_thoughts`、`understanding_level`、`user_notes`。`import_user_fields()` 只更新这三列，并以不可变 `paper_id` 匹配；重复、缺失或变化记录到 `library_meta.xlsx_conflicts`。

- [ ] **Step 4: 美化并实现安全定位**

生成器设置冻结窗格、自动筛选、表头颜色、系统/用户列区分、合理列宽和换行。定位路由只收 `paper_id`；引擎返回受管 workbook 和行号，Windows helper 使用参数数组或 COM API 打开并选中，不接受客户端路径/单元格。

- [ ] **Step 5: 验证并提交**

```powershell
python -m pytest engine\tests\test_xlsx_snapshot.py -q
node tests\excel-actions.mjs
git add engine src tests
git commit -m "功能：完善 Excel 维护与文献定位"
```

### Task 7: 整批 PDF 下载编排

**Files:**
- Create: `src/download_batch.ts`
- Modify: `src/routes.ts`
- Modify: `src/library_tools.ts`
- Create: `tests/download-batch.mjs`
- Modify: `tests/batch-contract.mjs`

- [ ] **Step 1: 写分层批次失败测试**

使用 fake provider 断言 20 篇只启动一次 Chrome，已有 PDF 被排除，挑战项集中处理：

```js
assert.equal(result.summary.skipped_existing, 3)
assert.equal(fakeChrome.launches, 1)
assert.deepEqual(result.challengePaperIds, ['p7', 'p9'])
assert.equal(result.children.find((x) => x.paperId === 'p2').status, 'completed')
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
node tests\download-batch.mjs
```

- [ ] **Step 3: 实现父任务和阶段屏障**

`submitDownloadBatch` 接受最多 100 个 `paper_id`，先并发 OA/HTTP，再对剩余项共用系统 Chrome Profile；只有明确 `anti_automation_challenge` 才进入 CloakBrowser 子集。失败不取消其他 child，重试只选非 completed 项。

- [ ] **Step 4: 暴露单篇和批量路由**

单篇下载复用一项批次服务。HTTP 只返回父任务 ID、脱敏汇总和 child 状态，不返回本地绝对 PDF 路径或浏览器 Profile。

- [ ] **Step 5: 验证并提交**

```powershell
node tests\download-batch.mjs
node tests\batch-contract.mjs
npm.cmd run typecheck
git add src tests
git commit -m "功能：加入分层批量 PDF 下载"
```

### Task 8: 设置页和紧凑文献页

**Files:**
- Modify: `client/client.js`
- Generate: `lib/client.js`
- Modify: `tests/client-ui-contract.mjs`
- Modify: `tests/client-actions.mjs`
- Modify: `tests/client-batch-actions.mjs`
- Create: `tests/settings-page-ui.mjs`

- [ ] **Step 1: 写 UI 合同失败测试**

断言源码存在两个视图、首次路由、两行条目和批准动作：

```js
for (const label of ['设置与状态', '获取 PDF', '打开 HTML', '定位 Excel', '下载缺失 PDF']) {
  assert.match(source, new RegExp(label))
}
for (const retired of ['飞书 ', '开始精读', '整理文章图表', '更多']) {
  assert.doesNotMatch(rowRenderer, new RegExp(retired))
}
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
node tests\client-ui-contract.mjs
node tests\settings-page-ui.mjs
```

- [ ] **Step 3: 实现设置页**

新增同级 conversation view。首次 snapshot 的 `show_settings=true` 时选择设置页并立即 mark-presented。渲染四张聚合状态卡和机构、下载、MinerU、本地库详情；输入 Key 使用 `type=password`，提交后立即 `value=''`，页面永不回显。

- [ ] **Step 4: 重写文献行而不改数据源**

使用语义结构：

```html
<article class="sr-paper-row">
  <input type="checkbox">
  <button class="sr-paper-title"></button>
  <div class="sr-paper-actions"></div>
  <div class="sr-paper-meta"></div>
</article>
```

标题最多两行；meta 只放作者、年份、期刊、三标签和按场景显示的文件夹/瞬时状态。普通筛选栏和批量栏互斥。窄屏把动作放到第二行，不设置页面级 `min-width`。

- [ ] **Step 5: 构建、验证并提交**

```powershell
npm.cmd run build:client
node tests\client-ui-contract.mjs
node tests\client-actions.mjs
node tests\client-batch-actions.mjs
node tests\settings-page-ui.mjs
npm.cmd run typecheck
git add client lib tests
git commit -m "界面：收敛文献导航并加入设置状态页"
```

### Task 9: 全量、真实 Bundle 与本地合并

**Files:**
- Modify: `README.md`, `docs/design.md`, `docs/features.md`, `docs/roadmap.md`, `docs/handoff-dsh-native.md`
- Modify: `docs/superpowers/plans/2026-08-27-v1-settings-library-ui.md`

- [ ] **Step 1: 运行代码与残余扫描**

```powershell
rg -n "sr_feishu|feishuConfig|FEISHU_APP|MinerU API-only|开始精读|整理文章图表" src client engine/src tests engine/tests README.md docs --glob "!docs/archive/**"
git diff --check
```

Expected: 无现行飞书/API-only/旧行级动作命中；允许设计文档在“移除”语境中出现飞书。

- [ ] **Step 2: 运行全量门禁**

```powershell
npm.cmd run build:ci
npm.cmd run typecheck
npm.cmd run test:offline
npm.cmd run verify:restart-recovery
```

Expected: 全部退出码为 0，测试不使用真实 Key、机构认证、MinerU 消费或用户数据。

- [ ] **Step 3: 真实 tarball 隔离验收**

使用临时 `DSH_HOME`、临时 data root、虚构工科题录和本地测试 PDF 打包并安装真实 tarball：

```powershell
$dsh = (Get-Command dsh -ErrorAction Stop).Source
$env:DSH_HOME = Join-Path $env:TEMP ("dsh-v1-release-" + [guid]::NewGuid().ToString("N"))
$env:USERPROFILE = Join-Path $env:DSH_HOME "user"
New-Item -ItemType Directory -Force -Path $env:USERPROFILE | Out-Null
$packed = npm.cmd pack --json --ignore-scripts | ConvertFrom-Json
$tarball = Join-Path (Get-Location) $packed[0].filename
& $dsh plugin --profile v1-release-test add $tarball --offline --ignore-scripts
& $dsh --profile v1-release-test --dump-config | Select-String '@dsh-external/dsh-scientific-reading'
```

随后在该临时 Profile 启动随机空闲端口，浏览器验证首次设置页、手动检测、两行列表、批量栏、PDF/HTML/Excel 动作和 1440×900、1280×720、900×720 三档无页面横向滚动。不得调用真实 MinerU 或机构访问；验收结束后停止宿主并删除本任务创建的临时 `DSH_HOME`。

- [ ] **Step 4: 更新执行记录并提交**

```powershell
git add README.md docs
git commit -m "文档：记录首版个人文献库验收结果"
```

- [ ] **Step 5: 本地合并回 main 并复测**

```powershell
git -C "D:\Vibe Coding\dsh-scientific-reading" merge --ff-only feature/v1-release
npm.cmd run build:ci
npm.cmd run test:offline
git status --short --branch
```

Expected: `main` 包含全部提交并通过全量测试；根目录原有未跟踪文档仍存在且未被提交。通过后删除任务 worktree 和分支，不推送 GitHub，除非用户另行要求。

## 执行记录

- 2026-08-27：在 `feature/v1-release` worktree 完成基线。`npm ci --ignore-scripts --legacy-peer-deps`、`npm run build:ci`、`npm run test:offline` 均通过；未使用真实 MinerU、机构认证或外部写入。
