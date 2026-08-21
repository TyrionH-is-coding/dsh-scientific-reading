# 插件 CI 与 DSH 版本锁定设计

## 目标

为 `dsh-scientific-reading` 建立可在 GitHub Actions 独立运行的最小插件门禁，并固定已经在本机真实验证过的 DSH 兼容基线，避免构建继续依赖某个未记录的本地 DSH 源码目录。

当前事实：

- Python 引擎仓库已有 Windows、Python 3.11、完整 pytest 和仓库边界 CI，不重复建设；
- 插件仓库没有 workflow、`package-lock.json` 或可独立安装的编译依赖；
- 当前真实运行的宿主为 `@deepseek-ai/dsh@0.1.0-rc.7`，`dsh-tools`、`dsh-llm`、`dsh-settings`、client runtime 与 UI slots 同为 rc.7；
- 当前插件已经在该宿主上通过 18 个工具、8 条路由和真实页面读回验证。

## 方案比较

### 方案 A：把完整 DSH 仓库作为 submodule 或 vendor 进插件

可以复现源码级构建，但会显著扩大仓库、升级流程和 CI 时间。当前插件只需要公开包的类型与运行接口，不值得引入整仓依赖。

### 方案 B：精确开发依赖 + lockfile + Windows CI

用 npm 公开包固定已验证的 rc.7 运行接口；为源码中的非 scoped import 使用 npm alias；生成 lockfile；CI 在 Windows 上安装、编译并运行现有离线门禁。

优点是改动小、与真实 Windows 运行环境一致、无需 DSH 源码 checkout。采用此方案。

### 方案 C：只在文档写“兼容 rc.7”

没有机器校验，依赖解析仍会漂移，不能解决问题。

## 依赖与兼容契约

`package.json` 增加显式 `dshCompatibility`：

```json
{
  "testedHost": "0.1.0-rc.7",
  "node": "22",
  "python": "3.11"
}
```

开发依赖使用精确版本：

- `@deepseek-ai/dsh`、`dsh-tools`、`dsh-llm`、`dsh-settings`：`0.1.0-rc.7`；
- `@deepseek-ai/cordis`：`4.0.1`；
- `@deepseek-ai/schemastery`：`3.18.1`；
- `cordis` 与 `schemastery` 使用 npm alias 指向上述 scoped 包，保持现有源码 import 不变；
- `@types/node`：`24.13.3`；TypeScript：`5.9.3`。

`package-lock.json` 是唯一依赖解析锁。`tests/dsh-compat.mjs` 读取 package 声明和实际安装的 package metadata，确保宿主与三个直接使用的 DSH 包均为同一 rc.7 基线；版本变化必须显式修改契约、lockfile 和文档。

这里锁定的是“已测试开发/CI 基线”，不是阻止用户未来试用更新宿主。现有 peer range 暂不收窄，避免把一次 CI 加固变成运行时兼容策略变更。

## CI

新增 `.github/workflows/ci.yml`：

1. `windows-latest`；
2. Node 22、Python 3.11；
3. `npm ci --ignore-scripts`；
4. TypeScript + client 构建；
5. client build、DSH compatibility、harness、飞书环境变量边界和 plugin-check。

CI 不执行：

- `verify-live.mjs`：需要真实运行的 DSH 与本地文献状态；
- `verify_restart_recovery.py`：需要相邻 Python 引擎运行时，属于跨仓本地集成门禁；
- 任何 PDF 下载、MinerU、机构认证或飞书写入。

Python 引擎自己的 workflow 继续负责完整 `pytest`。这样两个仓库各自独立，避免 CI 隐式依赖尚未发布的另一仓提交。

## 验收

1. 兼容性测试在缺少契约或版本不一致时失败；
2. `npm ci --ignore-scripts` 能从空 `node_modules` 复现安装；
3. TypeScript 与 client 构建成功；
4. 所有离线插件门禁通过，且不访问用户数据或飞书；
5. workflow 结构检查通过；
6. README、roadmap 和 handoff 明确 rc.7 是已测试基线，以及 CI 与本地集成门禁的边界。
