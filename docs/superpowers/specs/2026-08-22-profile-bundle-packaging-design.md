# DSH Profile Bundle 打包与隔离激活设计

## 1. 背景

当前插件已经具备可复现的 TypeScript/client 构建、离线测试、DSH
`0.1.0-rc.7` 兼容锁和本机运行验证，但 `package.json` 没有声明
`dsh.bundle.patch`，仓库也没有 `cordis.patch.yml`。因此现有代码能够在已配置的
宿主中运行，却还不是一个可由 `dsh plugin --profile ... add` 标准安装的
Profile Bundle。

本阶段参考 `omdsh-dev/plugin-template`、`omdsh-dev/dsh-plugin-dev` 和
`omdsh-dev/dsh-plugin-check` 的公开实践，只补交付闭环，不迁移整套模板。

## 2. 目标与成功标准

目标是让当前插件成为可独立打包、可安装并能在隔离 DSH profile 中证明激活的
Profile Bundle。

成功必须同时满足：

1. `package.json` 声明唯一的 Bundle Patch，且 patch 文件进入导出与 npm 包。
2. patch 只注册本插件，不修改 DSH 核心源码，也不包含本机绝对路径。
3. 离线测试能拒绝缺失、路径不一致、插件行错误或打包遗漏。
4. `npm pack --dry-run --json --ignore-scripts` 的清单包含插件运行产物、类型声明、
   运行时必需的 `scripts/scansci_wrap.py` 和 patch，不包含开发验证脚本、论文、密钥
   或运行数据。
5. 本地集成验收使用临时 DSH home/profile 完成
   `pack -> plugin add -> dump-config -> 发现插件行`，结束后删除临时状态。
6. 现有构建、18 个工具、8 条路由、飞书环境变量边界与重启恢复门禁保持通过。

## 3. 非目标

- 不升级 DSH `0.1.0-rc.7`、Node 22 或 Python 3.11 基线。
- 不发布 npm 包或 GitHub Release。
- 不改用户现有 `web`、`headless` profile 或正在运行的 DSH。
- 不执行真实飞书写入、论文下载、MinerU 长任务或机构认证。
- 不把仓库迁移为 pnpm/tsdown/vitest，也不重构已经工作的业务代码。
- 不把 `dsh-lark` 的聊天渠道或凭证存储方案并入本插件。

## 4. 设计

### 4.1 Bundle 契约

仓库根新增 `cordis.patch.yml`。它只贡献一个稳定、可搜索的插件行，并由该行加载
当前 npm 包的主入口。行标识必须归本插件所有，不能与宿主或其他插件共享。

`package.json` 增加：

- `dsh.bundle.patch` 指向 `./cordis.patch.yml`；
- `exports["./cordis.patch.yml"]`；
- `files` 中的 `cordis.patch.yml`，并把笼统的 `scripts` 目录收窄为运行时实际需要的
  `scripts/scansci_wrap.py`。

现有 `main`、`types`、client 声明、peerDependencies 和 rc.7 开发依赖保持不变。

### 4.2 离线契约与打包验证

新增一个 Node 测试负责读取 `package.json` 与 patch，检查三处路径一致、插件行唯一、
加载目标为当前包名，并拒绝绝对路径、父目录逃逸和用户目录字样。

另新增一个只读打包验证脚本，执行 npm 的 dry-run JSON 输出并检查最终文件集合。
验证面向“消费者实际拿到什么”，不以源码目录存在代替包内容证明。该脚本不得运行
安装生命周期脚本，也不得创建或发布 tarball。

这两项进入 `test:offline` 和 Windows CI；CI 继续不启动 DSH、不访问网络服务。

### 4.3 隔离 profile 集成验收

本地集成脚本从显式参数或当前已安装运行时解析 DSH CLI。它创建临时目录作为 DSH
home/profile，并在该目录内执行一次带 `--ignore-scripts` 的真实 `npm pack`，仅把生成的
本地 tarball 安装进去，然后读取 `--dump-config` 输出确认插件行生效。脚本不得复用或
写入用户的默认 `~/.dsh`，tarball 也随临时目录一并清理。

如果本机没有可用的 rc.7 DSH，脚本明确返回“运行时缺失”，而不是联网下载或静默
切换版本。该情况不影响离线 CI，但不能宣称本地激活验收完成。

### 4.4 错误边界

- manifest、patch 与包清单任一不一致即失败，并输出具体字段或缺失路径。
- dump-config 中零命中或多命中均失败；仅一个预期插件行才通过。
- 临时 profile 安装失败时保留受限诊断文本，但不得输出环境变量值或用户凭证。
- 清理只针对脚本创建且经绝对路径校验的临时目录。

## 5. 测试策略

实现遵循 TDD：

1. 先写 Bundle 契约测试，观察其因 patch/manifest 声明缺失而失败，再添加最小声明。
2. 先写包清单测试，观察其因 patch 未进入包而失败，再完成打包配置。
3. 对集成脚本使用可控的假 CLI 测试命令、隔离目录、零/多命中和清理边界；随后才用
   当前机器的真实 rc.7 DSH 做一次临时 profile 验收。
4. 最后重新执行干净安装、构建、全部离线门禁、重启恢复与现有 live 验证。

## 6. 交付与兼容策略

本阶段保持 `private: true`，证明“可安装与可打包”而不等于公开发布。DSH
`0.1.1-rc.1` 及上游模板的进一步迁移另立兼容阶段，在双版本验证通过前不替换当前
rc.7 基线。

阶段完成后按既定方式由 medium 子代理做规格与质量审核，本地快进合并到 `main`，
在 `main` 上复验并清理临时 worktree/分支；不自动推送远端。
