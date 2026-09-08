# 发布前核对：Deep Literature 系列

核对日期：2026-09-08。本页区分源码、自动化测试、用户实测与实际发布附件。

## 当前结论

核心流程已有工程验证；用户在本次对话中确认 **Mac 测试基本通过**。当前主要是最终源码和发行产物的收尾，尚不能将主线的新功能宣布为已随正式 v0.1.0 发布。

Deep Literature for DSH 原生插件与 Deep Literature for Codex 工作台继续分别发行。项目名称更新不改写既有插件标识、数据路径或公开附件。

## 已核对的事实

| 项目 | 证据与状态 |
| --- | --- |
| DSH 插件审查基线 | `87811b2ba243774215c81b792bd4258707684666`，[五平台 CI](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/actions/runs/34171621593)通过；本轮名称与文档改动另做构建及回归 |
| Codex 工作台已推送基线 | `bad9db3361e71b9fb7a06c5f6f81128e4d87dcc4`，[工作台与 OAuth CI](https://github.com/TyrionH-is-coding/deep-literature-for-codex/actions/runs/34175913099)通过 |
| Codex 工作台包安装 | 同一提交的[五平台安装检查](https://github.com/TyrionH-is-coding/deep-literature-for-codex/actions/runs/34175913172)全部通过，覆盖 Windows、两种 Mac 与两种 Linux |
| Mac 实机 | 用户于 2026-09-08 反馈“mac 测试基本已通过”；作为用户实测记录，不改写为所有模型、所有原生表格软件均已逐项通过 |
| 主线固定插件包 | B 随源码保存的 `inputs/scientific-reading.tgz` SHA256 与 pin 一致：`bda6d168a534e19b6e3e59fa02a6fe18c87fffa4c308294893fa2ed38ecb0580`；来源提交为 `f3e3298418ac17ca173727705eafb9755b5e2866` |
| 实际公开版本 | 原生插件 [rc.5](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/releases/tag/v0.1.0-rc.5)，Codex 工作台 [rc.6](https://github.com/TyrionH-is-coding/deep-literature-for-codex/releases/tag/v0.1.0-rc.6)；未发布正式 `v0.1.0` |

## 发行收尾

1. **确定最终源码。** 核对时 B 的下载流程仍有未提交的源码、Skill 和测试改动。它们不能借用上表旧提交的 CI 结果；完成合入后，以新的完整 SHA 作为发行来源。
2. **完成同一提交的 CI 和安装核验。** 待跑完的任务与失败任务不能算通过。Mac 已有用户反馈，保留实际版本与结果，不要求因为更新 README 重跑完整论文。
3. **对齐安装包与发布清单。** 本机旧 rc.8 候选包记录的 B 来源为 `8f66d4602be4fe5a572b7fb196f66558fe8c0fb3`，不是当前最终源码。后续有运行代码变化时，生成明确的新候选，逐文件与 SHA 回读；不覆盖已公开的同版本包。
4. **按依赖顺序发布。** 当前 B pin 指向 A rc.7，核对时该版本还没有公开 Release。发布最终插件附件后，再公开引用它的工作台安装包，并回读 tag、清单、附件与下载结果。

## 本轮改名范围

- 展示名称统一为 **Deep Literature for DSH**，首页增加 HTML Reader 示例、快速开始、使用与开发指南。
- DSH“关于”页的原生插件名称同步更新；Codex 工作台名称保持 Deep Literature for Codex。
- 插件包名 `@dsh-external/dsh-scientific-reading`、模式标识 `scientific-reading` 和既有文库路径保留兼容。
- 当前公开 Release 的标题与说明采用新名称；其 tag、安装包和附件哈希保持原样。较新主线的六项记录与翻译续接能力不写成旧附件已经包含。

旧版逐次修复与测试数字保留在原记录中，不作为这次所有场景重新运行的证明。

## 本轮改名验证

- Windows 本机完整 `npm test` 通过：Python 引擎 **514 passed / 3 skipped**，客户端构建、离线合同、独立 wheel 安装与源码一致性、资产检查通过。
- 当前新增或整理文档的本地链接、章节锚点和 UTF-8 检查通过，截图与用户原始 PNG 的完整 SHA256 一致。
- 本轮没有重新调用本人 OAuth、模型或 MinerU；Mac 基本通过的结论来源于用户反馈。
