# DSH Scientific Reading 当前技术设计

## 1. 产品模型

系统只有两个用户阶段：

1. **快速入库**：先用一个本地 SQLite 事务创建或复用记录，立即返回；题录补全、Abstract 翻译、XLSX 和可选飞书同步在后台继续。
2. **按需精读**：用户需要全文时再启动一个持久 parent job，依次取得并校验 PDF、运行 MinerU、逐块翻译、生成 reader 和导出图表资产。

快速入库不等待 PDF、MinerU、全文翻译或 HTML 渲染。全文重任务默认串行，批量请求按最多 100 篇分块，单篇失败不终止其他文献。

## 2. 责任边界

```text
DSH 文献页 / sr_* 工具
  -> TypeScript 插件
       参数校验、DSH 路由、导航 UI、合法 PDF provider
  -> Python 引擎
       SQLite、查重、任务、PDF 校验、MinerU、翻译、reader、XLSX/飞书派生
  -> 仓库外 data root
       library.sqlite、papers/、jobs/、配置和所有论文资产
```

- 插件不复制 SQLite 业务逻辑，也不保存浏览器凭据。
- Python 引擎不依赖 DSH UI，不读取浏览器 Profile。
- SQLite 是唯一事实来源；XLSX、飞书、metadata 和 manifest 都是派生视图或资产索引。
- 旧记录系统的字段只作只读兼容；当前运行入口不调用旧记录系统 API。

## 3. 数据与任务

`paper_id` 是本地稳定身份。查重优先 DOI、PMID 和 arXiv ID；无稳定标识时，只有题名、年份与作者组合明确才合并。文件夹为单归属，标签为多归属。

后台 job 和阶段结果写入 data root。相同论文、目标阶段和输入身份只存在一个有效任务；重启后从最后完成阶段恢复。XLSX 或飞书失败只改变各自派生状态，不回滚本地主库或精读结果。

## 4. 精读与资产合同

正式代次目录为：

```text
papers/<paper_id>/generations/<source_sha16>/
├─ source.pdf
├─ reading/reader.html
├─ reading/reader-manifest.json
└─ exports/
   ├─ figures/
   ├─ tables/
   ├─ captions.md
   └─ manifest.json
```

正式 reader 是 `reading/reader.html`；只读兼容回退仅允许同一 generation 的 `output/reader_full.html`。解析、PDF、reader 和导出路由都校验活动 generation、路径边界与 SHA，不按修改时间猜测最新文件。

图表导出包含 MinerU 明确标记的全部 Figure/Table，不让 AI 判断所谓关键图，也不猜测 bbox、图注或表格单元格。

## 5. 外部边界

- ScanSci 只作为合法 PDF provider；失败后单篇进入需要用户处理。
- 机构浏览器下载必须由用户逐篇选择，账号、Cookie、验证码和 MFA 不进入插件或日志。
- 飞书凭据只从宿主环境变量继承，首次启用不自动回填历史库，用户拥有字段永不进入更新 payload。
- 仓库只保存代码和文档；论文、解析产物、数据库、密钥和真实配置均在仓库外。

实现与验收证据见[两阶段/三阶段总索引](superpowers/plans/2026-08-23-two-stage-literature-workflow-index.md)。
