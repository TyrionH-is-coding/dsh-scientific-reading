# A 0.1 OA 获取与设置收口实施计划

> **For agentic workers:** 使用 executing-plans 在当前已授权任务内逐项执行。保留脏工作树；不提交、推送、发版或触及真实实例。

**Goal:** 落实 PA-01、PA-03：A 只自动获取 OA，失败等待本地 PDF；设置只保留密钥、资产位置和必要状态。

**Architecture:** 固定 wrapper 仅调用 arXiv、Europe PMC OA 和显式邮箱启用的 Unpaywall HTTP 来源，不进入 ScanSci 综合 fetch、机构配置、浏览器或缓存。单篇、批次和精读共享这一入口。旧机构工具和路由退出注册，旧配置不能改变获取边界。

**Tech Stack:** TypeScript、原生 JavaScript、Python、Node 合同测试、pytest。

## 1. 备份与边界回归

- [x] 记录 Git 状态；逐文件备份到 `C:/Users/15694/.codex/backups/dsh-scientific-reading/20260905-oa-only-settings`，记录 SHA-256。
- [x] 先补失败用例：批次 OA 失败不调用机构依赖；固定 wrapper 不加载综合下载/机构入口；配置 `legalOnly=false` 不改变 OA 限制。
- [x] 运行 `node tests/download-batch.mjs` 和 `node scripts/run-python.mjs -m pytest -q engine/tests/test_scansci_oa_boundary.py`，确认失败对应旧行为。

## 2. 最小 OA 实现

- [x] 修改 `scripts/scansci_wrap.py`：使用 `try_arxiv` / `try_unpaywall`，固定新配置且不读用户配置；成功文件必须位于本次临时目录并满足 PDF 签名/结尾检查。
- [x] 修改 `src/cli.ts`：下载必须经过 wrapper；wrapper 缺失不回退到通用 CLI；下载配置只放插件数据根，固定 OA-only。
- [x] 修改 `src/download_batch.ts`：所有 OA 不可用项返回 `manual_required`，异常不阻断其他项，不存在机构升级分支。
- [x] 修改 `src/tools.ts`、预设、`src/routes.ts`、`client/client.js` 与 PDF gate：退出机构入口；保留重试 OA 与现有本地 PDF 导入。
- [x] 编译 TypeScript，再运行边界、下载批次与精读入口测试。
- [x] 固定官方 ScanSci 1.9.0 最小运行闭包与 SHA，在全新托管 venv 中验证安装、入口和公开 OA PDF；记录 Europe PMC 实际全文超时，不宣称成功。

## 3. 设置与状态

- [x] 修改 `engine/tests/test_environment_status.py`、设置路由与 UI 合同，先确认旧实现失败。
- [x] 修改状态服务：资产根和 SQLite 路径可见；仅接受 download/mineru_local/mineru_api 检测；返回固定 OA 模式；MinerU 已配置不表示 API 已实测。
- [x] 修改 `src/status_routes.ts` 和 `client/client.js`：移除高校路由/表单；保留安全保存、替换、删除密钥和现有 CSRF。
- [x] 运行设置路由、密钥边界与 UI 合同测试。

## 4. 回归与候选包

- [x] 调整只因本次产品边界变化而过时的工具清单和文案断言。
- [x] 运行 `npm test`、`npm run verify:restart-recovery`；不运行真实付费服务或长期宿主实例。
- [x] 构建并生成独立候选 tarball；记录固定路径和 SHA，更新执行证据；版本按父任务指示对齐为 `0.1.0-rc.1`，由父任务最终审查。

已确认假设：OA 首版覆盖 arXiv 与可从 DOI/论文 URL 识别出的 Europe PMC OA / 显式配置的 Unpaywall OA；无法识别的 URL 进入待补 PDF。现有上传、SQLite、摘要、MinerU、Reader、Excel、备份恢复和搜索仍沿用已有合同。

执行更新（2026-09-06）：已与分类作用域改动统一构建并完成全量回归、重启恢复与归档读回；源码和 `0.1.0-rc.1` 私有候选已冻结交父任务。详见[执行记录](../executions/2026-09-06-oa-only-settings.md)。
