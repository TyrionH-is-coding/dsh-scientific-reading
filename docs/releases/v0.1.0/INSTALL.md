# Windows 安装指南

这是原生插件 A 的 **0.1.0-rc.1** 安装指南。该 Release 已撤回为草稿，当前供持有冻结构建包的测试用户使用；公开状态见[发布修复记录](RELEASE_GATE.md)。测试前核对 `.tgz` 与交付方提供的 `SHA256SUMS.txt`。

## 需要准备什么

目标环境为 Windows 10/11 x64、Node.js 22、Python 3.11，以及 DeepSeek Harness `0.1.0-rc.7`。Python 3.11 是当前 CI 的目标环境；本机历史验收也使用过 Python 3.12。最终支持范围以该 Release 的实际验收记录为准。

已有 DSH 时先查看版本，关闭准备安装插件的 DSH 实例。原生插件安装到用户选定的 DSH 环境；独立捆绑、完全隔离 DSH 的 Codex 工作台 B 不包含在此包中。

普通用户需要下载 Release 的插件 `.tgz` 和 `SHA256SUMS.txt`。GitHub 自动生成的 Source code 压缩包是源码，不是可直接安装的插件包。

## 1. 检查基础依赖

在 PowerShell 中执行：

```powershell
node --version
npm.cmd --version
py -3.11 --version
pnpm.cmd --version
dsh --version
```

缺少 Node.js 或 Python 时，可使用 Windows 软件包管理器安装：

```powershell
winget install --id OpenJS.NodeJS.22 -e
winget install --id Python.Python.3.11 -e
```

安装后重新打开 PowerShell。缺少 pnpm 或首次安装 DSH 时执行：

```powershell
npm.cmd install --global pnpm@11 @deepseek-ai/dsh@0.1.0-rc.7
if ($LASTEXITCODE -ne 0) { throw 'DSH 或 pnpm 安装失败，请保留错误信息。' }
```

已有不同版本的 DSH 时先核对兼容性和现有配置，不直接覆盖升级。网络下载或宿主依赖安装可能耗时，本文不承诺固定安装时长。

## 2. 下载并核对安装包

将已取得的 `dsh-external-dsh-scientific-reading-0.1.0-rc.1.tgz` 和配套 `SHA256SUMS.txt` 放在同一目录。尚未取得安装包时，等待[项目 Releases](https://github.com/TyrionH-is-coding/dsh-scientific-reading/releases)正式公开候选；草稿对普通访问者不可下载。GitHub 自动生成的 Source code 压缩包不能安装。

下面默认使用“下载”目录；如果保存到别处，先修改 `$releaseFolder`。

```powershell
$releaseFolder = Join-Path $env:USERPROFILE 'Downloads'
$releaseArchive = Join-Path $releaseFolder 'dsh-external-dsh-scientific-reading-0.1.0-rc.1.tgz'
$releaseChecksums = Join-Path $releaseFolder 'SHA256SUMS.txt'
$releaseName = [System.IO.Path]::GetFileName($releaseArchive)
$releaseLine = @(Get-Content -LiteralPath $releaseChecksums -Encoding UTF8 | Where-Object {
    $_ -match ('^[0-9a-fA-F]{64}  ' + [regex]::Escape($releaseName) + '$')
})
if ($releaseLine.Count -ne 1) { throw '未找到唯一的安装包校验记录。' }
$releaseExpected = $releaseLine[0].Substring(0, 64)
$releaseActual = (Get-FileHash -LiteralPath $releaseArchive -Algorithm SHA256).Hash
if ($releaseActual -ne $releaseExpected) { throw '安装包校验不一致，请重新下载。' }
'安装包 SHA-256 匹配。'
```

校验用于确认下载完整并与发布记录一致，不能代替来源真实性判断；安装包与校验表均应从同一个项目 Release 获取。

## 3. 安装到 DSH

下面使用默认 DSH 环境的 `web` Profile。若原有 DSH 使用自定义 `DSH_HOME`，应在相同环境中执行安装和启动；本指南不会更改它。

```powershell
dsh plugin --profile web add $releaseArchive --ignore-scripts
if ($LASTEXITCODE -ne 0) { throw '插件安装失败。' }
```

插件包已包含构建好的前端、预设和 Python wheel；无需克隆第二个引擎仓库。首次初始化仍可能从 Python 包源下载运行依赖。OA 初始化使用随包 `scripts/oa-requirements.txt` 的固定官方 wheel URL 与 SHA，安装到本插件托管虚拟环境，不复用或更改用户级 ScanSci、机构配置及浏览器环境。

启动该 Profile：

```powershell
dsh --profile web --host 127.0.0.1 --port 3080
```

浏览器打开 `http://127.0.0.1:3080`。如果 3080 已有另一实例，先确认属于哪个 DSH；不要终止不明进程。可以为本实例选择其他空闲端口，并使用相应地址。

## 4. 完成首次使用

1. 在 DSH 原生模型设置中配置模型服务。
2. 新建会话，在模式菜单选择 **文献模式**。切换普通聊天模式后不显示文献工具是预期行为。
3. 打开 **文献** 和 **设置与状态**，确认当前数据位置；默认是 `%USERPROFILE%\scientific-reading-data`。
4. 在文献对话中输入：“检查并初始化文献工作环境，完成后告诉我哪些步骤已经可用。”初始化需要安装依赖时，以工具返回的具体结果为准。
5. 先录入一篇自己的测试文献，确认标题和文献条目出现。需要全文解析时，在设置页保存 MinerU API Key，再用自己可分享给解析服务的 PDF 做一次解析。

“已保存 Key”只说明凭据已配置；一次真实解析完成才证明服务和当次额度可用。API Key 填在设置页，模型凭据填在 DSH 模型设置，不需要发到对话或问题反馈中。

安装后继续看[五个起步任务](USAGE.md)。遇到问题见[故障处理](SUPPORT.md)。

OA 来源：arXiv 可直接使用；DOI 通过 Europe PMC 明确 OA 全文链接尝试获取。Unpaywall 只在用户显式配置 `UNPAYWALL_EMAIL` 时启用，不提供虚构默认邮箱。元数据命中不等于 PDF 已取得；认证、挑战页或无有效 PDF 均回到待补本地 PDF。
