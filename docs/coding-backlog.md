# Coding Backlog（当前仓库）

> 本清单只记录当前单仓库中尚未完成、且已能从源码边界说明的工作。代码整合见[可靠性整合验收记录](superpowers/executions/2026-09-05-reliability-integration.md)，最新结果见[内容保真与发布验收](superpowers/executions/2026-09-05-content-fidelity-release.md)。历史双仓库计划、独立 demo 和旧快照不在这里维护。

## 版本安排（2026-09-05）

- **0.1 优先发布**：原生插件收口为 OA 自动获取和本地 PDF 补入，设置仅保留 MinerU Key、资产位置和必要状态；沿用固定 Excel 与默认 Reader。优先完成主链路、内容完整性、笔记保留和实包验收。
- **0.2 用户自定义与文献雷达，待做**：以下项目不作为 0.1 发布前置条件，也不在首版预先搭建配置、模板或雷达框架。

| 待办 | 范围 | 状态 |
| --- | --- | --- |
| Excel 展示方案 | 现有字段显隐、顺序、显示名、列宽、换行，保存与恢复方案 | 0.2 待做 |
| 自定义研究字段 | 字段定义与人工填写；需要 AI 提取时另定义来源和证据合同 | 0.2 待做 |
| HTML 模板 | HTML/CSS 与外观配置，导入、预览、应用、恢复默认，复用已有解析与译文 | 0.2 待做 |
| 分类展示方案 | 全库默认与分类方案选择，沿用分类权限 | 0.2 待做 |
| 文献雷达 | Agent 协助确认方向，多来源发现与去重，解释相关性和质量依据，候选筛选及按配置增量扫描 | 0.2 待做 |

本表跟踪项目 A；新的 Codex 工作台 B 及共享关系见[双项目工程规划](superpowers/specs/2026-09-05-two-product-literature-architecture.md)。具体发布边界见[发布路线](roadmap.md)。两个项目独立发布，B 和上述 0.2 待办均不阻塞 A 的 0.1。

文献雷达的[现有项目与 Skill 调研](../outputs/literature-radar-research-2026-09-05/调研报告.md)已完成，包含固定提交、许可、复用建议、公开接口与纯函数探针。优先参考 paperradar 的编排、医学雷达的检索/增量思路及具体方向/证据判断 Skill；完整宿主接入与真实推荐质量尚待 0.2 验收，不把调研完成记为功能完成。

## 本轮已整合与验收

- 设置与状态页、文献模式预设、文献库导航、分层 PDF 下载、双 MinerU provider、DPAPI 密钥边界、generation reader 路由、Reader review 工具和 Excel 白名单回写已进入当前代码。
- Reader review 的三个 fixture 已完成结构检查和桌面、平板、手机布局的浏览器检查；实际 tarball 已在临时 DSH Profile 跑通正式 Reader HTTP 路由。真实 MinerU、机构登录及真实 Excel 占用/回写仍需单独验收。
- 引擎阶段记录已包含 `started_at`/`finished_at`；旧 backlog 中“stage 计时缺失”不再是当前缺陷。
- CLI UTF-8 输出、MinerU 本机探测顺序、`MINERU_FORMULA_CH_SUPPORT`、旧资产兼容、公式/MathML 插入和 stale translation 处理已进入当前代码；是否满足发布门禁不能仅凭源码判断。
- A08 的 PubMed 混合 XML 标题/摘要丢字已修复；A07 固定 13 个合成样本并复用 Reader 双语样本，分别记录文字、语义边界与视觉结果。摘要 HTTP 接口已兼容数据库中的空派生状态。该最小样本集不等于完整质量基准。

## 近期真实验收

### R1. Reader 视觉与大文档性能

- 已审计一个真实 12 页历史 generation 并实际浏览旧 Reader，发现缺图、缺参考文献正文和错误上标等问题。现已从验证后的历史缓存生成可审核候选：115 行精确复用、15 行待翻译、66 行待审核；没有生成新 Reader，**R1 未关闭**。补齐可追溯译文与审核后仍需核查图文、公式、引用和论断支持，详见[R1 候选重建](superpowers/executions/2026-09-05-r1-candidate-rebuild.md)。
- 选取图表较多、内嵌资产较大的非敏感样本，记录首屏、滚动和内存表现；不把静态 HTML 检查当作视觉验收。

### R2. 宿主与数据边界

- 隔离 DSH Profile 已通过正式 Reader 路由、无效条目 404、停止/重启后 Reader SHA 不变，以及文献库、摘要和设置状态 HTTP 读回。本轮另覆盖实际包上的合成整库恢复、文献检索和证据跳转；恢复演练范围与最终包 SHA 见[阅读资产验收记录](superpowers/executions/2026-09-05-recoverable-reading-assets.md)。真实用户库灾难恢复演练及其余交互仍需对应验收，未替换正式 Profile。
- 本机 MinerU 与真实 DSH 已知 PDF 流程已有[单独记录](superpowers/executions/2026-09-05-known-pdf-dsh-acceptance.md)，不等于真实长论文语义通过。API MinerU、provider 切换、真实 Excel 占用 pending 和 GUI 白名单字段回写仍未覆盖；本轮没有连接的 Excel 控制会话。

### 阅读资产工程项

- A02 已实现整库冻结、版本化备份与新/空目录恢复，覆盖用户字段、多 generation、未完成任务、Reader 与 SHA 读回；恢复不切换正式库或自动继续任务。
- A03 已实现 PDF/source map 双版本定位、确认与动态回跳、旧定位保留及可审核候选计划。R1 得到 184 个 source map blocks 与 196 行计划（含额外 12 行 caption）；15 行待翻译、66 行待审核，R1 仍未关闭。
- A04 第一层已实现元数据、英中摘要、确认结论检索及分类片段/证据状态。正文、译文全库覆盖和向量检索不在本次交付范围。
- 全套、实际安装包、恢复库 HTTP 与浏览器证据统一见[阅读资产验收记录](superpowers/executions/2026-09-05-recoverable-reading-assets.md)。原先 R2 的一般 Reader 验收不代替本次恢复库验收。

## 产品候选

### P1. 本地阅读状态

SQLite 已有流水线 `status` 和三个 Excel 用户字段，但“读没读/理解程度”的产品字段尚未定义。需要先确定字段、筛选语义、迁移和 Excel 所有权，再实现文献页与工具支持。

### P2. 学习闭环

在 P1 稳定后评估一句话理解卡、回顾队列和组会一页纸；不引入飞书同步依赖，也不把 AI 推断写成论文事实。

### P3. 研究工作流增强

按需求评估轻量本地笔记读取、跨论文比较、多个 PDF 附件和中文检索分词；每项都需独立设计和验收，不作为当前 V1 已交付能力。

## 明确推迟

- 文献发现与方向相关的增量推荐已归入上方 0.2 文献雷达；BibTeX/引用导出、通用订阅聚合、逐篇 JSON 证据卡、自动综述和跨论文证据综合继续保留为后续候选。
- 任意字段双向同步、批量删除、多个 MinerU/全文翻译任务并行、AI 自动挑选关键图和 DSH 页面内嵌整篇 reader。
