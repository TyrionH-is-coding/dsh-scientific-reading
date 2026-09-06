# v0.1 发布候选交付

本目录是两个 0.1 产品的范围与验收入口，以及原生插件 A 的用户指南。当前候选用 SHA 区分，不能只凭版本号认定是同一个包。

- A：`0.1.0-rc.1` 已撤回为草稿，暂未公开放行，见[发布修复记录](RELEASE_GATE.md)。
- A 旧 tag 对应源码：`a0db7cf8eba434c493ac2cb5e3d3d22ad403ab7a`；已通过 CI 的修复提交：`401e98256d42e10650b5ec71a475634c1aedfd1b`。两者尚未对齐。
- B 私有 prerelease：https://github.com/TyrionH-is-coding/codex-scientific-reading/releases/tag/v0.1.0-rc.1
- B 对应源码：`645d41a19fc879b0dd362245aaf8b03f5961651e`

- **A：DSH Scientific Reading**，以已构建的 `.tgz` 安装到用户自己的 DSH。自动获取仅限 OA，支持补入本地 PDF。
- **B：Codex 文献工作台**，独立的 Windows 安装包和 Codex Skill，内含固定 A 包与隔离 DSH；Codex 管全库，DSH 持久会话管理各分类。B 自己提供安装、模型、迁移、升级与卸载指南。

两者都以 SQLite 保存事实，Excel 为有限回写的派生视图。自定义 Excel/HTML 与文献雷达在 0.2。

| 材料 | 用途 |
| --- | --- |
| [0.1 实现与验收状态](IMPLEMENTATION_GAPS.md) | 按产品确认已补齐内容及真实验证边界 |
| [A 安装指南](INSTALL.md) | 校验 tarball、安装 DSH 插件、首次配置 |
| [A 使用与数据维护](USAGE.md) | 入库、摘要、PDF、精读、Excel、备份恢复 |
| [故障处理与数据流向](SUPPORT.md) | 错误处理、联网内容与反馈 |
| [发布说明](RELEASE_NOTES.md) | 可复制的 Release 文案；公开前填最终证据 |
| [发布检查清单](RELEASE_CHECKLIST.md) | 冻结、同包验收与公开步骤 |
| [组件核对](DEPENDENCIES.md) | 许可与固定依赖 |

普通用户使用构建产物，无需自行编译 wheel。首发可用 GitHub Release 分发，npm 注册表发布不是前置条件，`private: true` 不妨碍 tarball 安装。

真实网络、本人 OAuth、MinerU、论文内容和安装程序属于不同验收层；安装成功不自动代表其余全部完成。最终附件应伴随明确的验收记录和 SHA256SUMS。原工程代码和用户库保留，当前工作以可审阅的源码快照追踪，不虚构已提交的 Git SHA。
