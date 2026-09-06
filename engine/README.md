# DSH Scientific Reading Engine

本目录是插件内置的 Python 引擎，负责 SQLite 文献库、摘要与全文任务、本机/API MinerU、Reader/资产导出，以及 Excel 派生视图和白名单回写。飞书不属于当前运行主链。

引擎随插件单仓库构建并打包；从仓库根目录运行 `npm.cmd run build:ci`。开发者可在本目录创建专用 `.venv`，并通过 `PYTHON` 或 `SCIENTIFIC_READING_PYTHON` 指定解释器后运行仓库脚本。自动测试和真实宿主验收的当前结果见[可靠性整合验收记录](../docs/superpowers/executions/2026-09-05-reliability-integration.md)。

整库维护与阅读资产入口（使用已安装当前 wheel 的 Python）：

```powershell
python -m scientific_reading --data-root C:\ReadingData library-backup --output C:\ReadingBackups\library.zip
python -m scientific_reading --data-root C:\ReadingData library-restore --archive C:\ReadingBackups\library.zip --target C:\ReadingRestored
python -m scientific_reading --data-root C:\ReadingRestored library-search-rebuild
python -m scientific_reading --data-root C:\ReadingRestored library-list-v2 --query "IL-6"
python -m scientific_reading --data-root C:\ReadingRestored evidence-locate --help
python -m scientific_reading --data-root C:\ReadingRestored resolve-conclusion --help
python -m scientific_reading --data-root C:\ReadingRestored candidate-rebuild --help
```

`--output` 不得位于源库内或覆盖现有包；`--target` 必须不存在或为空。恢复只改新目录，未完成任务转为需显式继续，凭据重新配置。数据库 schema 为 v4，备份合同为 `scientific-reading-backup-v1`，定位为 `evidence-locator-v1`。检索派生索引可重建，不代表正文或译文全库检索。
