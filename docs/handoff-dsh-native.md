# DSH Scientific Reading 开发交接

## 当前职责

- `dsh-scientific-reading`：DSH 工具、参数校验、HTTP/文件路由、文献导航 UI、合法 PDF provider 和真实 Bundle 验收。
- `Scientific-Reading-for-Newbies`：SQLite、查重、文件夹/标签、持久任务、PDF 校验、MinerU、翻译、reader、资产、XLSX 与飞书领域合同。
- `%USERPROFILE%\scientific-reading-data`：默认数据根；论文、数据库、任务、配置和所有资产与仓库分离。

`client/client.js` 是前端规范源，`lib/client.js` 由构建生成，不直接编辑。两个仓库都可能存在其他任务 worktree；开发前先检查 `git status` 和 `git worktree list`。

## 本地开发顺序

1. 在隔离 worktree 修改 Python 引擎并运行定向及全量 pytest。
2. 让插件通过 `PYTHONPATH` 或设置中的 `enginePython` 指向待测引擎。
3. 运行插件 client 构建、TypeScript 检查和完整离线测试。
4. 使用临时 data root、虚构工科题录、本地 PDF 和 fake client 做真实 Bundle、HTTP 与浏览器 QA。
5. 只有隔离验收全部通过后，才本地合并回两个 `main`、在 `main` 重测并清理任务 worktree。
6. 更新 persistent Profile 前备份 tarball、配置和 SQLite，并记录 SHA；安装真实 tarball 后完成停止/重启读回。

## 常用验证

Python 引擎：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
Remove-Item Env:FEISHU_APP_ID -ErrorAction SilentlyContinue
Remove-Item Env:FEISHU_APP_SECRET -ErrorAction SilentlyContinue
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& '.\.venv\Scripts\python.exe' -m pytest -q
git diff --check
```

DSH 插件：

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run typecheck
npm.cmd run test:offline
npm.cmd run verify:profile-bundle -- --dsh-bin '<DSH bin.js 绝对路径>'
npm.cmd run verify:profile-runtime -- --dsh-bin '<DSH bin.js 绝对路径>'
npm.cmd run verify:navigation-runtime -- --dsh-bin '<DSH bin.js 绝对路径>' --engine-python '<引擎 python.exe>'
npm.cmd run verify:restart-recovery
git diff --check
```

离线测试必须清空真实飞书凭据。Windows 生产子进程启动边界必须保持无窗口参数，避免 worker/CLI 重启时弹出终端。

## 三层 Bundle 门禁

1. `test:offline` 验证构建、假宿主合同和安全边界，但不证明真实 DSH 能加载 tarball。
2. `verify:profile-bundle` 用真实 DSH 在临时 `DSH_HOME` 离线安装 tarball，并要求插件配置唯一。
3. `verify:profile-runtime`、导航 runtime 与浏览器 QA 验证宿主实际导入、路由、页面和关闭清理。

开发注入会覆盖同名 tarball。persistent 安装前必须确认同名开发登记已注销，安装目录不是 junction，并从实际 tarball 读回 client 与 package 身份。

## 安全和所有权

- 测试只用 fake 飞书 client；真实写入必须获得针对当次操作的明确授权并写后读回。
- 机构访问必须由用户逐篇选择；插件不保存账号、Cookie、验证码、MFA 或浏览器 Profile。
- App Secret 只存在于启动 DSH 的宿主环境，不进入配置、SQLite、XLSX、日志或 HTTP 响应。
- 旧 PDF、MinerU、reader 和历史浅读只读索引，不移动、不删除、不无故重算。
- 不 push GitHub，除非用户另行要求。

当前架构和能力分别见[技术设计](design.md)与[功能清单](features.md)；历史方案位于[归档目录](archive/README.md)。
