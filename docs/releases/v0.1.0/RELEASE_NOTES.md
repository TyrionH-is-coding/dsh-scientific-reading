# DSH Scientific Reading v0.1.0-rc.1

> 当前为撤回后的草稿文案。仅在放行提交 CI 通过、tag 与 prerelease 对齐并读回后称为已公开；状态见 [RELEASE_GATE.md](RELEASE_GATE.md)。

在 DSH 的文献模式中，完成从题录入库、正文获取到双语精读和个人笔记的日常流程。

## 这一版提供什么

- **文献入库与整理**：录入 DOI、链接或题名，查重并补全能核实的题录与摘要；用文件夹、标签和搜索管理文献。
- **摘要与正文阅读**：先读双语摘要；取得 PDF 后按需进行 MinerU 解析、翻译与审核，生成保留来源关系的 Reader。
- **OA 获取与本地补入**：自动寻找 OA 正文；其他文献可补入用户已有的 PDF。
- **图表与笔记**：导出正文图表，在固定格式 Excel 中记录个人思考、理解程度和笔记。
- **本地数据维护**：SQLite 保存主库，Excel 和 Reader 作为派生产物；任务按阶段继续，整库备份可恢复到新目录。

模型使用 DSH 原生设置。MinerU API Key 在插件设置页保存；已有并经过验证的本机解析环境可按支持条件使用。

## 安装

面向 Windows 用户提供构建好的插件 `.tgz`，包含 Python 引擎 wheel。持有冻结包的测试用户须核对配套的 `SHA256SUMS.txt`；其他用户等待候选重新公开后再下载，无需自行克隆、编译插件。

[安装指南](https://github.com/TyrionH-is-coding/dsh-scientific-reading/blob/main/docs/releases/v0.1.0/INSTALL.md) · [使用与数据维护](https://github.com/TyrionH-is-coding/dsh-scientific-reading/blob/main/docs/releases/v0.1.0/USAGE.md) · [问题处理](https://github.com/TyrionH-is-coding/dsh-scientific-reading/blob/main/docs/releases/v0.1.0/SUPPORT.md)

依赖条件见安装指南；`RELEASE-MANIFEST.json` 记录版本、已记录的来源快照和实际安装包校验信息。已有用户请先备份数据，安装后抽查原有文献、Reader 和笔记。

## 使用范围

- 本包是 **DSH 原生插件 A**。机构认证与授权浏览器获取属于独立的 **Codex 工作台 B**，不包含在本包中。
- 来源缺少摘要或 OA 正文时会保留待补状态；不能保证每篇文献都有完整元信息或可自动取得 PDF。
- 保存 MinerU Key 不等于解析已成功；API 解析和模型调用使用各自的网络服务及额度。
- Reader 和译文需对照原文核查。原文定位可追溯不等于科学论断经过自动验证。
- Excel 首版采用固定格式，仅规定的用户字段允许回写；当前搜索范围不等于全文/译文的全库语义搜索。

自定义 Excel、HTML 模板与文献雷达已列入 **v0.2**，将在首版之后继续推进。

遇到问题可通过[问题反馈表单](https://github.com/TyrionH-is-coding/dsh-scientific-reading/issues/new?template=bug_report.yml)提供版本、复现步骤与错误码。
