# 可靠性修复与已有分支整合计划

> **For agentic workers:** Use the existing scoped parallel agents and verify the integrated working tree before completion. 用户已要求一次完成本次确定需要的修复，无需分批确认。

**Goal:** 修复已确认的数据保护、任务完成和恢复缺陷，将已完成的设置/讨论与 Reader 审核代码整合到当前工作树，并统一当前文档和验收证据。

**Architecture:** 保持 DSH 为唯一宿主、SQLite 为事实源、Excel 为派生表及三个用户字段的回写入口。使用三方内容合并保留现有未提交改动；不新增独立产品形态。

**Tech Stack:** TypeScript、Node.js 22、DSH 0.1.0-rc.7、Python、SQLite、openpyxl、pytest。

## 执行与验收

- [x] 保存本轮开始时 41 个未提交文件及 SHA-256。备份目录：`C:\Users\15694\.codex\backups\dsh-scientific-reading\20260905-100152`。保留分支、工作树和用户现有资产，不自动提交或推送。
- [x] 整合 `feature/settings-review-mvp` 和 `feature/reader-review-loop` 的已完成改动。逐文件比较 merge-base、当前工作树和分支内容；手工处理 `client/client.js`、`src/index.ts`、`src/preset.ts`、`tests/harness.mjs` 与 `package.json`；由构建重生成 `lib/client.js`。验收：类型检查、预设边界、review 路由/工具、Reader fixture/CLI/包边界合同。
- [x] 修复 `engine/src/scientific_reading/xlsx_snapshot.py` 的重复表头、重复隐藏身份行和损坏工作簿问题。先在 `engine/tests/test_xlsx_snapshot.py` 复现，再检查原文件字节不变、无错误归属、修复后可重试；保留已完成的 pending/worker 状态修复。
- [x] 修复 `engine/src/scientific_reading/reading_pipeline.py` 的源文件变更时错误复用旧任务、派生更新阶段永远等待问题；修复 `worker.py` 覆盖文献就绪状态；校验 `package_manifest.py` 拒绝包外路径。每项在对应 Python 测试中先复现，验证合法旧行为仍可用。
- [x] 修复 `src/download_batch.ts` 的单篇预检查异常中断整批问题。在 `tests/download-batch.mjs` 注入一篇读取/附件检查异常，验证其余文献继续且汇总准确；检查任务查询与重启后的状态展示。
- [x] 校准 `README.md`、`engine/README.md`、`docs/README.md`、`docs/design.md`、`docs/features.md`、`docs/roadmap.md`、`docs/handoff-dsh-native.md`、`docs/coding-backlog.md`。删除当前入口中的双仓库、飞书运行能力、过期 Git/PID 和“已实现仍待实现”说法，保留历史归档。
- [x] 统一验证：`npm run typecheck`，构建，完整 `engine/tests`，`npm run test:offline`，重启恢复，临时安装 wheel 和真实 tarball 的隔离 DSH HTTP 验收，Reader fixture 与浏览器检查。测试使用临时数据，不访问真实文献库或调用收费模型/MinerU 服务。
- [x] 对最终代码差异做独立复核；修复新发现的确定问题后重跑受影响检查，将结果写入 `docs/superpowers/executions/2026-09-05-reliability-integration.md`，更新本清单。

## 判断边界

源码、离线合同、隔离宿主、浏览器检查分别记录；结构正确不能替代真实 PDF、翻译与学术内容的人工语义评估。真实机构登录及真实 MinerU 服务需要用户环境和服务授权，不将未执行项计为通过。
