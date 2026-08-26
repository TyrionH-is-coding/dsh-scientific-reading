# 单仓库运行时瘦身设计

## 目标

`dsh-scientific-reading` 成为可独立克隆、构建、安装和运行的唯一仓库。仓库只包含当前产品主链；历史实现不进入 npm 包、Python wheel、运行时命令、测试夹具或安装文档。

## 当前功能白名单

1. 元数据入库、SQLite 文献库、文件夹与分类、批量任务。
2. ScanSci 合法 PDF 获取与用户手动附加 PDF。
3. 摘要浅读及 agent 提交门。
4. MinerU 官方 API 全文解析、翻译、精读 HTML、图片/表格资产与导出。
5. 后台任务、恢复、状态查询和无窗口子进程。
6. 飞书派生同步、显式重同步及当前字段合同。
7. DSH 阅读页、批量页和当前 reader 路由。

插件公开工具只保留：

`sr_setup`、`sr_scansci_status`、`sr_scansci_fetch`、`sr_scansci_login`、`sr_scansci_set_school`、`sr_ingest`、`sr_library_list`、`sr_folder_manage`、`sr_classification_apply`、`sr_classification_undo`、`sr_start_full_read`、`sr_continue_full_read`、`sr_attach_pdf`、`sr_export_assets`、`sr_job_status`、`sr_feishu_resync`，以及 agent gate 必需的内部工具 `sr_abstract_submit`。

## 明确删除

- 独立 `Scientific-Reading-for-Newbies` 仓库路径和任何相邻 worktree 探测。
- PyMuPDF/fitz、本地快速 PDF 文本解析、bbox 再裁图和 PyMuPDF 缓存身份。
- MinerU 本地 CLI/可执行文件探测；MinerU API 是唯一全文解析器。
- Zotero 模块、插件、桥接、命令、字段别名、脚本和测试。
- 旧 `quick_read` 固定结构流程；当前“浅读”仅指摘要浅读。
- 旧 parse/full-read CLI 和插件工具，以及重复的 init/check/ensure/attach/search 入口。
- 旧飞书 preview/direct-sync 插件入口；保留当前自动派生同步与显式 resync。
- legacy audit、旧根目录 reader fallback、历史 benchmark 和迁移运行时代码。
- 仅证明上述旧功能的测试、示例和文档。

## PDF 与 MinerU 边界

本地预检只验证文件存在、大小、`%PDF-` 签名和 SHA-256；不做正文提取、身份判断或渲染。加密、损坏和页面结构由 MinerU API 的正式结果判定。标题/DOI 等身份在 MinerU 标准化结果生成后核验。图表只使用 MinerU 返回资产，Pillow 仅验证图片可读性。

## 单仓库结构

```text
dsh-scientific-reading/
├─ src/                       # DSH 插件
├─ client/
├─ engine/
│  ├─ pyproject.toml
│  ├─ src/scientific_reading/ # 当前 Python 引擎白名单
│  ├─ reader/
│  └─ tests/
├─ dist/python/               # 构建生成的 wheel，不提交缓存
├─ tests/                     # 插件与单仓库集成测试
├─ LICENSE
├─ THIRD_PARTY_NOTICES.md
└─ MIGRATION.md
```

`sr_setup` 从插件自身携带的 wheel 安装用户数据目录下的虚拟环境。开发覆盖项 `enginePython` 只供显式调试，不再作为默认安装前提。

## 数据边界

不删除、不移动用户数据目录、旧 generation、旧 PDF 或旧 HTML。新运行时只索引当前 generation 合同；历史产物留在磁盘，由迁移说明解释，不把旧执行代码带回仓库。

## 验收

1. 残余扫描拒绝外部引擎路径、PyMuPDF/fitz、Zotero、本地 MinerU 和旧工具名。
2. Python wheel 可在干净虚拟环境安装、导入并运行 CLI。
3. npm tarball 同时包含插件、wheel、LICENSE 和第三方声明。
4. CI 在单次 checkout 内完成 Python、Node、集成和打包测试。
5. 临时 data root 跑通虚构工科论文的入库、摘要、fake MinerU API、reader、资产导出和 fake 飞书链路。
6. 当前主链通过后本地合并 main，再在 main 复验；旧引擎仓库本轮不删除。
