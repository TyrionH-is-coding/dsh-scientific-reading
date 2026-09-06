# 第三方组件与发行核对

本表根据当前 `package.json`、`package-lock.json`、`engine/pyproject.toml` 及已安装依赖的许可文件整理，供 v0.1.0 收口后按实际包复核。它不是完整 SBOM，也不替代发行包随附的许可文本。

## 当前组成

| 组件 | 声明/约束 | 获取与分发方式 |
| --- | --- | --- |
| 本项目插件与 Python 引擎 | BSD-3-Clause；根目录保留完整 LICENSE | 本项目 `.tgz` 内含引擎 wheel |
| Beautiful Soup 4 | `>=4.12,<5`；现有声明为 MIT | 引擎运行依赖，初始化时由 Python 包源获取 |
| latex2mathml | `>=3.81,<4`；现有声明为 MIT | 同上 |
| Pillow | `>=12,<13`；现有声明为 HPND | 同上；最终依实际 wheel 的许可文件核对 |
| openpyxl | `>=3.1,<4`；现有声明为 MIT | 同上 |
| DSH 宿主与相关包 | 当前目标 `0.1.0-rc.7`；抽查 dsh、dsh-agent、dsh-tools 为 MIT | 用户的 DSH 环境提供；A 不捆绑整个宿主 |
| Cordis / Schemastery | 当前 lockfile 与许可文件为 MIT | DSH 插件依赖/宿主提供，按实际打包方式保留声明 |
| MinerU API | 外部服务 | 按用户配置调用，不把服务实现打进插件包 |
| 可选本机 MinerU | 独立安装环境 | 不因支持调用就宣称其二进制随包分发；若改变分发方式，重新核对许可与依赖 |
| 0.2 调研中的项目/Skills | 各自许可，包含非商业或未确认的候选 | 尚未成为 v0.1 运行依赖，调研源码不随产品包分发 |

## 最终包核对（2026-09-06）

- 最终 A tarball SHA 为 `15f752f359ed2865a32671e1c7e0240bb74ad22033b706029efcbc7110672c59`，实际包含 LICENSE、THIRD_PARTY_NOTICES.md 和 MIGRATION.md。
- wheel 的实际 METADATA 为 `dsh-scientific-reading-engine 0.1.0`，Python `>=3.11`；运行依赖为 Beautiful Soup、latex2mathml、Pillow、openpyxl，与上表约束一致。pytest 仅为 dev extra。
- 随包第三方通知明确 MinerU API 为外部调用，不分发本地 CLI；OA 使用官方 ScanSci PDF 1.9.0 的受限模块，Apache-2.0，官方 wheel 及最小 Requests/Beautiful Soup 闭包 SHA 固定在 `scripts/oa-requirements.txt`。未安装机构/浏览器来源及未使用 extras。
- A 的通用运行依赖仍为版本范围。B 则固定 14 个 Python wheel、npm lock 和私有 Node/Python；两者的可复现条件不同，不将 A 的范围声明冒充完整锁文件。
- 附件只分发程序、文档、锁文件和许可，不包含研究 PDF、用户库、账号信息或浏览器 Profile。A 源码已公开；Release 已撤回为草稿，后续公开放行仍须核对准确提交、附件 SHA 和来源清单。

这里只准备核对材料，不改变项目许可证或新增运行依赖。若后续发布 Codex 工作台 B，捆绑的 DSH、运行时和 OAuth 组件应另做发行清单，不沿用 A 的清单冒充完整覆盖。
