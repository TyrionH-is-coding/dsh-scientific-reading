# DSH Scientific Reading 首个发布版技术设计

## 1. 发布目标

首个发布版只把个人文献库的长期主链路做好：

1. **快速入库**：用户在 DSH 对话中提供 DOI、PMID、arXiv ID、题名或作者，系统先用一个 SQLite 事务创建或复用记录并立即返回。
2. **按需下载**：用户可在对话中发起单篇或批量下载，也可在【文献】页为未取得 PDF 的记录点击单篇或批量下载。
3. **生成精读 HTML**：取得并校验 PDF 后，由持久 parent job 依次完成 MinerU、翻译和 reader 生成。
4. **维护个人文献库**：SQLite 保存系统事实；DSH 文献页负责导航和归类；美观的 Excel 工作簿提供长期表格化查看，并只允许白名单用户字段回写。

首个发布版不包含文献发现、推荐、引用网络、知识图谱或综述生成。飞书退出产品路线；现存飞书代码仅作为待删除的遗留实现，不属于发布验收合同。

## 2. 用户界面责任

### DSH 对话

对话是主要执行入口，负责入库、智能归类、批量下载、启动精读、复杂异常处理和任务汇总。批量任务按整批逐层推进，不逐篇打断用户。

### DSH 文献页

文献页的主要责任是资料库导航：全部文献、待归类、文件夹、标签、搜索、筛选、分页、批量归类，以及打开 Abstract、PDF、精读 HTML 和资产目录。

下载是一个明确例外：没有 PDF 的单篇记录显示【下载 PDF】，选择多篇后可执行【下载缺失 PDF】。页面只显示队列状态和汇总，不暴露 provider、浏览器后端或重试参数，也不扩展成通用流水线控制台。

### Reader

Reader 只负责阅读正文、目录、双语内容、重点和图表，不承担文献管理、下载配置或后台任务控制。

## 3. 责任边界

```text
DSH 对话 / 文献页
  -> TypeScript 插件
       参数校验、DSH 路由、导航 UI、单篇/批量下载入口
  -> Python 引擎
       SQLite、查重、任务、PDF 校验、MinerU、翻译、reader、Excel 派生与白名单回写
  -> 仓库外 data root
       library.sqlite、scientific-reading.xlsx、papers/、jobs/ 和所有论文资产
```

- 插件不复制 SQLite 业务逻辑，也不保存浏览器凭据。
- Python 引擎不依赖 DSH UI，不读取用户日常 Chrome Profile。
- SQLite 是系统事实来源；Excel、metadata 和 manifest 是派生视图或资产索引。
- Excel 不是第二套完整数据库，只能通过明确白名单回写用户拥有字段。
- 旧记录系统和飞书字段只作迁移期只读兼容；当前发布路线不再扩展它们。

## 4. Excel 所有权合同

工作簿固定生成到 `<data-root>/library/scientific-reading.xlsx`，使用稳定 `paper_id` 关联 SQLite。

- **系统字段**：题名、作者、主要研究单位、年份、期刊、DOI/PMID/arXiv ID、Abstract、来源链接、PDF/精读状态、PDF/HTML/资产路径、错误状态和更新时间。它们从 SQLite 生成，Excel 修改不得覆盖主库。
- **首批用户字段**：个人思考、个人理解程度和用户笔记。只有这些字段允许从 Excel 白名单回写 SQLite。
- 文件被 Excel 占用时，刷新或回写进入 pending，稍后重试；不得回滚入库、下载或精读结果。
- 回写前按 `paper_id` 校验行身份；缺失、重复或被修改的稳定标识使该行停止回写并报告，不猜测匹配。
- 生成器负责冻结窗格、筛选、列宽、换行、状态样式和用户字段提示，保证工作簿适合长期阅读，而不是导出一张原始数据表。

文件夹和标签继续通过文献页或对话维护，不在首批 Excel 回写白名单内。以后新增任何可回写列，都必须先明确所有权、冲突规则和迁移方式。

## 5. 下载与批量合同

下载按整批分层执行：

1. 对全部缺失 PDF 的目标尝试 Open Access 和普通 HTTP；
2. 聚合剩余项目，只启动一次系统 Chrome 专用 Profile 完成机构访问；
3. 明确检测到反自动化挑战的项目集中挂起，不影响其他文献；
4. 只有用户安装过可选 CloakBrowser 增强包时，才对挑战子集重试；
5. 最终未取得 PDF 的项目进入手动挂接状态。

单篇失败不终止整批。已有 PDF 自动排除，重试只处理未成功项目。页面和对话统一显示 OA/HTTP 成功、Chrome 成功、反自动化待处理、等待手动 PDF 和最终失败的汇总状态。

## 6. 数据与任务

`paper_id` 是本地稳定身份。查重优先 DOI、PMID 和 arXiv ID；无稳定标识时，只有题名、年份与作者组合明确才合并。文件夹为单归属，标签为多归属。

后台 job 和阶段结果写入 data root。相同论文、目标阶段和输入身份只存在一个有效任务；重启后从最后完成阶段恢复。Excel 刷新或回写失败只改变 Excel 派生状态，不回滚本地主库、PDF 或精读结果。

## 7. 精读与资产合同

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

## 8. 下一版本方向

下一版本在稳定个人文献库之上增加两个独立能力：

1. **上游发现与推荐**：从研究问题、关键词和种子论文生成候选文献，保留来源和推荐理由，由用户决定是否入库；推荐结果不得自动触发付费或机构下载。
2. **下游 JSON 证据卡**：每篇已读文章生成带版本合同和来源定位的 `.json` 证据卡，供综述写作、证据比较及其他下游任务读取。证据卡是派生产物，不替代 SQLite、PDF 或 reader。

这两个方向不进入首个发布版的实现和验收范围。
