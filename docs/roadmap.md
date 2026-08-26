# DSH Scientific Reading 当前技术路线

## 已完成基线

### 两阶段产品流程

- 快速写入本地主库，后台补全 Abstract、XLSX 和可选飞书派生。
- 用户按需启动全文精读，持久 parent job 负责 PDF、MinerU、翻译、reader 与资产导出。

### 三阶段工程交付

- Phase 1：SQLite 主库、查重、Abstract 浅读、文件夹/标签、XLSX 与飞书所有权合同。
- Phase 2：精读状态机、合法 PDF 接入、generation 资产、全文翻译和 Figure/Table 导出。
- Phase 3：宽版文献导航、批量操作、旧资产审计、真实 Bundle、HTTP、浏览器和 persistent Profile 验收。

完整提交和测试证据见[总执行索引](superpowers/plans/2026-08-23-two-stage-literature-workflow-index.md)。

## 后续独立范围

1. **期刊正文优先 reader builder 迁移**：把已验证演示合同迁入生产构建器，保留正文优先、左栏导读、行内重点和英文来源定位。设计见[期刊正文优先文档](superpowers/specs/2026-08-24-reader-html-periodical-first-design.md)。
2. **首次真实飞书写入验收**：只有用户针对当次写入明确授权后，才用一篇非敏感测试文献验证 create、重复同步和完整读回。
3. **文献发现与待读循环**：把上游搜索和现有入库/精读链路连接起来，先生成候选记录，由用户决定是否加入待读，不让 AI 判断直接触发 PDF 下载。

### 文献发现与待读循环（尚未实现）

计划数据流：

```text
研究问题
  -> AI 拆分主题、扩展查询词
  -> OpenAlex / Semantic Scholar / PubMed / arXiv / Crossref / Zotero
  -> DOI / PMID / arXiv ID / OpenAlex ID 规范化、来源记录与去重
  -> 候选文献收件箱
  -> 用户加入待读或忽略
  -> 现有 PDF 获取 / MinerU API / reader / 飞书链路
  -> 从已读种子论文沿引用与被引用网络继续发现
```

初版保持轻量：

- AI 只负责查询扩展、相关性解释和排序建议，不自动下载候选论文。
- 每条候选记录必须保留稳定标识、发现来源和引用网络路径；合并来源不能丢失 provenance。
- 不整体嵌入 ARIS、ScholarQA、OpenScholar 或其他大型研究框架，只借鉴多来源降级、查询重排和证据追溯设计。
- Citation Gecko 只作为种子论文引用网络扩展的参考；ASReview 只作为积累足够用户“相关/不相关”反馈后的排序参考。
- 用户选择进入待读后，才交给当前 DSH 后台链路处理 PDF、MinerU、HTML 和飞书。

以上三项都不是当前已交付基线的缺口，应分别设计、实现和验收。

## 明确不恢复或不扩展

- 不恢复旧记录系统运行链或一次性迁移工具。
- 不恢复旧版固定章节浅读。
- 不让 AI 判断关键图，不批量执行机构浏览器下载。
- 不实现 SQLite/XLSX/飞书双向同步或飞书个人字段回写。
- 不自动改用户飞书表结构；当前版本尚不提供推荐、引用网络或知识图谱运行入口。
