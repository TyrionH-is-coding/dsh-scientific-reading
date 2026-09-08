# Deep Literature for DSH · 公开测试版

Deep Literature for DSH 是 DSH 原生文献插件：在对话中查重入库、获取 OA 正文或补入本地 PDF，生成双语 HTML 阅读页，并用本地文献库和 Excel 保存个人笔记。

项目原名为 DSH Scientific Reading。本次更新发布页名称与使用说明，**本 Release 仍是 v0.1.0-rc.5，tag 和安装包保持不变**。

[项目简介](https://github.com/TyrionH-is-coding/deep-literature-for-dsh#readme) · [使用指南](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/blob/main/docs/getting-started.md) · [反馈问题](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/issues)

## 安装

准备 DSH、Node.js 22、Python 3.11、可用模型配置和 MinerU API Key。当前验证宿主为 DSH 0.1.0-rc.7。

下载下方插件 `dsh-external-dsh-scientific-reading-0.1.0-rc.5.tgz` 和 `SHA256SUMS.txt`，核对 SHA256。停止目标 DSH 后，在同一环境安装：

~~~sh
dsh plugin --profile web add "/绝对路径/dsh-external-dsh-scientific-reading-0.1.0-rc.5.tgz" --ignore-scripts
~~~

重新启动该 Profile，新建会话并选择 **文献模式**。模型在 DSH 原生设置中配置，MinerU Key 在插件“设置与状态”页保存。

插件包 SHA256：

~~~text
318814ec542de94a47cd2855b21d0f7af9778b22b283d3995d0c499a3465e2fd
~~~

## 这个安装包能做什么

- DOI、链接或题名入库，查重并补全可核实的题录与摘要。
- 自动获取有开放来源依据的 OA 正文，或补入本地 PDF；机构认证下载由本人处理。
- MinerU 解析、分批翻译与复核，生成中英对照 HTML Reader 和图表资产。
- 本地 SQLite 文献库与 Excel 总表；该旧包提供个人思考、理解程度、用户笔记三项回写。

主线中的六项个人记录、新设置行布局和翻译草稿续接属于后续改动，以对应新包验收与发布为准。

## 本版修复

修复 Deep Literature for Codex #6：MinerU 无可用内容的空图表条目记录页码、原始索引和复核警告，不再中断全部归一化。缺图但有正文、标题、脚注、图表 content 或结构化内容时仍报告完整性错误；非法路径、实际资产缺失和哈希不匹配仍失败。

原始 JSON、来源哈希与后续正文索引保持可追溯。空解析条目不能证明原 PDF 没有内容或已无损跨页合并，报告要求核对对应页及相邻条目。

## 验证范围

该版本的原有合成回归记录为：专项 90 项、完整 Python 引擎 484 passed / 3 skipped，本地 npm test 通过。按用户确认，本轮不等待原论文 PDF，不宣称该论文原任务和最终 Reader 已复测。

当前发布页整理没有重打包，不把后续主线测试或 Mac 用户反馈追记成此附件的全量回归。[版本与证据核对](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/blob/main/docs/release-readiness.md)

使用自己的模型与 MinerU 账号额度；本原生插件不要求 Codex 订阅。想由 Codex 统筹并准备独立工作台，可使用 [Deep Literature for Codex](https://github.com/TyrionH-is-coding/deep-literature-for-codex)。
