# @dsh-external/dsh-scientific-reading

文献工作流插件（Phase 0：下载段已可用）。把 Scientific-Reading-for-Newbies 的
完整文献流水线搬进 DSH：下载 → 解析 → 入库 → 笔记。

继续在 DSH 内原生开发前，请先阅读 [`docs/handoff-dsh-native.md`](docs/handoff-dsh-native.md)；该文档记录当前实际基线、验证命令、飞书最终结构和已知旧文档偏差。

## 当前状态（Phase 0）

已注入 DSH 并热重载验证，工具：

| 工具 | 作用 |
|---|---|
| `sr_setup` | 检查/安装 scansci-pdf + 合法来源配置（默认关 Sci-Hub） |
| `sr_scansci_status` | 下载器健康 + 学校/输出目录/合法开关总览 |
| `sr_scansci_fetch` | DOI/URL → PDF 落盘 + 元数据 JSON |
| `sr_scansci_login` | 机构登录（CARSI/WebVPN/Cookie，浏览器弹出，密码不经过插件） |
| `sr_scansci_set_school` | 设置学校 |

## 构建与注入

客户端唯一规范源码是 `client/client.js`，不要直接编辑 `lib/client.js`。修改客户端后运行
`node scripts/build-client.mjs`，并以 `node scripts/build-client.mjs --check` 确认产物最新；
`plugin-check` 也会比较源码和产物，过期时失败。

当前已测试宿主基线为 `@deepseek-ai/dsh@0.1.0-rc.7`，CI 使用 Node 22、Python 3.11
和 `package-lock.json` 中的精确插件依赖。首次安装或 lockfile 更新后可在空依赖目录复现：

```powershell
npm.cmd ci --ignore-scripts --legacy-peer-deps
npm.cmd run build:ci
npm.cmd run test:offline
```

`--legacy-peer-deps` 是有意的：插件 CI 只安装编译与挂载冒烟实际加载的最小闭包，
其余 peer 由真实 DSH 宿主提供；不会把接近 200 个宿主包复制进插件开发依赖。

```powershell
# 注入/重载（DSH dev 工具）
dev_build_plugin / dev_inject_plugin / dev_reload_package
```

## 垫片说明

`scripts/scansci_wrap.py` 修复 scansci-pdf 1.9.0 的三个问题（仅本插件调用路径生效）：

1. 未配置机构时跳过浏览器登录（防空 URL 崩溃）；
2. arXiv 成功返回补 `path` 键（原返回 `file`，fetcher 读 `path` 导致 PDF 永不认领）；
3. 强制 UTF-8 输出（中文 Windows 控制台 GBK 报错）。

## Phase 2（文献页）

- 宿主路由 `/sr/api/*`：论文列表（含 job 实时状态富化）/详情/新建/下载/挂PDF/解析/浅读/任务/笔记/精读HTML
- 文献页标签：`conversation.view`（id: literature, order: 20），三栏界面（筛选/表格/详情+操作），纯 DOM 实现
- 设置卡片：`settings.plugin.item`（key: scientific-reading），设置页【插件】tab 可编辑数据目录/学校/合法来源等
- 库状态同步：worker 阶段完成后自动更新 SQLite（parsed_fast/quick_read_ready…）
- client 渲染契约：`__ModuleLoader__.load` id = 包名；组件用 React 元素 + ref 桥接真实 DOM（React 拒绝裸 DOM 节点）

## 飞书凭证

设置卡片只保存仓库外 `feishu-config-v1` JSON 路径。App ID 与 App Secret 不进入
插件设置或 JSON；请在启动 DSH 的宿主环境中设置后重启 DSH：

```ini
FEISHU_APP_ID=你的AppID
FEISHU_APP_SECRET=你的AppSecret
```

同步时先运行零网络的 `sr_feishu_preview`；仅在核对预览后，针对该篇论文以
`confirm=true` 调用 `sr_feishu_sync`。

从旧版升级时，如果曾在设置卡片填写过 `feishuAppId` 或 `feishuAppSecret`，请在
DSH 停止后从 `scientific-reading` 设置分节删除这两个旧键。新版本不会读取它们；
也不会自动改写用户设置文件。当前配置从未填写过这两个字段时无需处理。

## 验证

```powershell
node tests\ci-workflow.mjs       # CI 只能执行离线门禁
node tests\dsh-compat.mjs        # rc.7 兼容契约与安装版本
node scripts\plugin-check.mjs   # 插件健康门禁（构建/产物/边界）
node tests\feishu-env-only.mjs  # 飞书凭证仅继承宿主环境
node tests\harness.mjs          # 挂载冒烟（工具/路由注册 + 重复挂载容忍）
node scripts\verify-live.mjs    # 上线验证（路由/文献页 client/库状态）
```

GitHub Actions 只运行构建与上述离线门禁。`verify-live.mjs` 和
`verify:restart-recovery` 依赖真实 DSH 或相邻 Python 引擎，继续作为本地集成验收；
Python 全量测试由引擎仓库自己的 workflow 负责。

## 路线图

见 `docs/roadmap.md`：Phase 0 下载段 ✅ → Phase 1 本地文献库（SQLite，替代 Zotero）✅
→ Phase 2 【文献】标签页（代码完成，待宿主重载验证）→ Phase 3 飞书/精读/迁移。
