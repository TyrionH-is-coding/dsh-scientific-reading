# Deep Literature for DSH 使用指南

[项目首页](../README.md) · [Excel 管理](excel-library.md) · [开发与验证](development.md)

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Windows x64、macOS Apple Silicon / Intel、Linux x64 / ARM64 |
| Node.js | 22 |
| Python | 3.11，可从当前 DSH 进程环境中发现 |
| DSH | 当前验证的宿主为 `@deepseek-ai/dsh@0.1.0-rc.7` |
| 模型 | 在 DSH 原生设置中配置可用模型服务 |
| PDF 解析 | MinerU API Key，或已配置且验证可用的本机 MinerU |

跨平台 CI 包括 Windows、两种 macOS 架构和两种 Linux 架构；原生应用和真实账号操作的证据分开记录。Linux 保存 MinerU Key 需要可用、已解锁的 Secret Service。

已有 DSH 时先运行 `dsh --version` 核对版本。新装 DSH 的命令为：

~~~sh
npm install --global pnpm@11 @deepseek-ai/dsh@0.1.0-rc.7
~~~

## 下载并校验插件

从 [GitHub Releases](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/releases)下载插件 `.tgz` 与同一 Release 的 `SHA256SUMS.txt`。GitHub 自动生成的 Source code 压缩包是源码，不是已构建插件。

Windows PowerShell：

~~~powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:/下载目录/下载的插件.tgz'
~~~

macOS：

~~~sh
shasum -a 256 '/下载目录/下载的插件.tgz'
~~~

Linux：

~~~sh
sha256sum '/下载目录/下载的插件.tgz'
~~~

核对结果与清单中的完整哈希一致。文件名仍使用历史包名，这是为兼容已有安装保留的技术标识。

## 安装与启动

先保存工作并正常停止目标 DSH，在该实例原来的环境中安装：

~~~sh
dsh plugin --profile web add "/绝对路径/下载的插件.tgz" --ignore-scripts
dsh --profile web --dump-config
~~~

配置中应出现 `@dsh-external/dsh-scientific-reading`。自定义 Profile 或 `DSH_HOME` 的用户沿用原值，不要把插件装到另一个实例。

使用原来的 DSH 启动方式重新启动；新装的 web Profile 可以运行：

~~~sh
dsh --profile web --host 127.0.0.1 --port 3080
~~~

进入网页后选择工作区，新建会话并选择 **文献模式**。其他模式不会启用文献工具。安装、更新或移除 Bundle 后都需要重启对应 Profile。

在对话中先请模型“检查并初始化文献插件运行环境”。`sr_setup` 会准备数据目录内的托管 Python 环境；插件随包提供引擎 wheel，普通用户无需克隆引擎仓库。OA 依赖按随包清单安装。

## 首次配置

1. 在 DSH 原生设置中配置模型服务，再在会话模型选择器中选中它。
2. 从 [MinerU 官网](https://mineru.net/)的“API 管理 → Token”取得免费 Token。
3. 在文献插件的“设置与状态”中保存 MinerU Key。只填写 Token，不附加 `Bearer` 或整段示例代码。
4. 先用一篇公开论文验证 PDF 解析、翻译与 Reader 生成。

当前 MinerU 官方限制为每个账号每天 1,000 页最高优先级解析、单文件最多 200 页和 200 MB；超出每日额度后降低优先级。具体以账号页面为准。[官方说明](https://mineru.net/apiManage/docs)（2026-09-08 核对）

MinerU Key 在 Windows 使用 DPAPI、macOS 使用 Keychain、Linux 使用 Secret Service。模型服务凭据由 DSH 的相应提供方管理。API 解析会上传 PDF 至 MinerU；模型请求会发送完成任务所需的文本。

已有本机 MinerU 的用户可以使用本地解析。插件检测并调用已有环境，不自动安装 CUDA 或下载 MinerU 模型。解析后端在任务创建时确定，失败后保留断点。

## 入库与生成 HTML

在文献模式中发送 DOI、PMID、arXiv 链接或题名，请模型先查重、核对题录和补摘要。题名有歧义时先选择正确记录，缺失摘要保持待补。

~~~text
建立“入门阅读”文件夹，把这篇文献加入其中：
https://doi.org/10.48550/arXiv.1706.03762

尝试获取 OA 正文，取得后开始全文精读。
生成中英对照 HTML 阅读页，保留正文图表、公式与来源位置。
完成后打开 Reader；中途需要补文件或操作时告诉我。
~~~

自动 OA 获取失败时，由本人在有权访问的渠道取得 PDF，再向同一会话提供文件完整路径：

~~~text
把这个本地 PDF 补入刚才那篇文献，校验后继续原精读任务。
~~~

插件不读取机构登录状态或浏览器凭据。没有 PDF 时可以先管理题录、分类和已有摘要。

任务中断后查询并继续原任务。阅读页和图表以实际解析结果为依据，译文、公式和科学结论应结合原文核对。

## 维护 Excel

在文献页或设置页打开当前库的总表，在允许编辑的个人记录列中填写内容。保存并关闭工作簿后，在文献对话中请求同步与刷新。

公开旧包支持三项个人记录；当前主线扩展为六项记录及阅读成果、图表索引，具体以安装版本为准。使用新表时见 [Excel 指南](excel-library.md)，不要修改隐藏身份信息，也不要只对部分列排序。

文件被占用或出现冲突时先保留原表，按回执处理后重试。生成 Reader 不等于用户已经读完论文。

## 备份更新与卸载

- **备份**：在文献对话中请求把完整文献库备份到库外的新目录。备份包含数据库、PDF、Reader 和相关资产。
- **恢复**：恢复到新建或空目录，校验后再决定切换数据位置。重新配置模型与 MinerU，明确继续未完成的任务。
- **更新**：先备份并停止 DSH，核对新包哈希后，在同一 Profile 执行安装命令，重启后确认原文献与笔记仍在。
- **回退**：旧程序未必支持新数据库格式。使用升级前备份恢复到新目录，不让旧程序直接写入新版文献库。

正常停止对应 DSH 后可卸载插件：

~~~sh
dsh plugin --profile web remove @dsh-external/dsh-scientific-reading
~~~

卸载插件不主动删除文献数据。原来的文献模式预设可能保留；需要清理时先核对实际归属。

## 排错

| 现象 | 先检查 |
| --- | --- |
| 找不到文献模式或文献页 | 是否装入正确 Profile，以及安装后是否重启 |
| 模型没有文献工具 | 当前会话是否选择文献模式 |
| 找不到 Python 引擎 | Python 3.11 是否可用，是否完成环境初始化 |
| MinerU Key 已保存但任务失败 | 区分“已配置”和真实调用结果，按错误回执继续原任务 |
| Excel 显示待同步 | 保存并关闭表格；出现冲突时保留原文件 |
| 升级后启动失败 | DSH 版本和插件是否为已验证组合；保留错误与备份 |

反馈时附上系统、插件版本、DSH 版本、操作步骤与错误文字。[提交问题](https://github.com/TyrionH-is-coding/deep-literature-for-dsh/issues)
