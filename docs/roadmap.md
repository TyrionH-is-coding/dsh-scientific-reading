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

这两项不是当前已交付基线的缺口，应分别设计、实现和验收。

## 明确不恢复或不扩展

- 不恢复旧记录系统运行链或一次性迁移工具。
- 不恢复旧版固定章节浅读。
- 不让 AI 判断关键图，不批量执行机构浏览器下载。
- 不实现 SQLite/XLSX/飞书双向同步或飞书个人字段回写。
- 不自动改用户飞书表结构，不增加推荐、引用网络或知识图谱。
