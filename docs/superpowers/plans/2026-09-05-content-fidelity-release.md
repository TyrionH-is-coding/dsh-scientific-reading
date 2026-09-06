# 第一轮内容保真与发布验收计划

范围：A08 的 PubMed 混合 XML 缺陷、A07 的最小质量样本，以及 A01 现有 R1/R2 验收。保持当前工作树、DSH、SQLite、generation 和 Excel 回写边界；不实现 A02/A03/A04。

## 假设与提取规则

- PubMed 主 `Abstract` 是本轮 `abstract_en` 的来源，不合并 `OtherAbstract` 或从标题补摘要；文章原文语言不等于主摘要语言。
- 内联标签按文档顺序展开所有文字及 tail，不在标签边界额外插空格。普通单段格式兼容；多段摘要保留顺序、段落及存在的 Label。
- 上下标的字符保留，但纯文本字段不携带排版。MathML 的文本展开不等于公式语义转换，必须在样本说明中明确限制。
- 真实 generation 的文件存在、文本对应、译文论断支持和视觉表现分别记录；没有真实长文档或必要应用条件时保留验收缺口。

## 实施与验收清单

- [x] 复查 Git 与依据；保存 303 个现有文件的 SHA、185 个脏文件副本及当前 diff。备份：`C:\Users\15694\.codex\backups\dsh-scientific-reading\20260905-191242-content-fidelity`。
- [x] 固定版本的 13 个合成 XML 样本；先失败再最小修复，最终 metadata 16 项、与 Reader 合计 28 项通过。
- [x] 复用 Reader fixture 并完成本轮单案例三档视觉检查；真实历史 generation 的内容缺陷和候选身份拒绝已记录。完成检查不等于 R1 通过。
- [x] 完整检查 256 passed、1 skipped 与 39 条离线命令通过；补充摘要 HTTP 修复后再次通过全部 39 条离线命令。最终安装 wheel 的导入路径与源码 SHA 一致，16 项回归通过。
- [x] 最终 tarball 在隔离 Profile/数据根通过来源、三个相关 HTTP 入口、Reader HTTP 和停止/重启；未替换原 Profile，3080 状态前后不变。
- [x] 独立复核已处理空段边界与非法摘要状态；[验收记录](../executions/2026-09-05-content-fidelity-release.md)已记录命令、包 SHA、样本版本、保留证据与未覆盖项，backlog 已更新。

历史调研目录只读，不运行会覆写原结果的调研脚本。真实机构认证、付费 API 与用户工作簿不在自动验证范围。
