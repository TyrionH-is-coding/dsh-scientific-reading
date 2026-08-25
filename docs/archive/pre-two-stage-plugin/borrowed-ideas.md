# 借鉴清单（Borrowed Ideas）—— 来自 omdsh-dev 社区生态

> 记录从 [omdsh-dev（Oh My DSH）](https://github.com/omdsh-dev) 社区仓库中考察后
> 决定借鉴的**功能**与**开发流程**，以及明确**不借鉴**的部分。
> 考察时间：2026-08-21（社区版本较新，引用前先看对应仓库当前 README）。

---

## 1. 来源背景

omdsh-dev = DeepSeek Harness 的非官方社区插件生态（107 个公开仓库），
覆盖 UI 工作台 / 渠道集成 / Agent 编排 / 记忆监控 / 开发基建五类。
价值：社区踩坑经验 + 官方未覆盖能力的民间实现，可直接对照学习。

## 2. 社区仓库分类概览

| 类别 | 代表仓库 | 用途 |
|---|---|---|
| 工作台/UI | DSH-better-sidebar、dsh-tianshu-tui、dsh-genui、dsh-annotation | 侧边栏框架、终端 UI、对话内 UI、选中批注 |
| 渠道/集成 | dsh-lark、dsh-notification、dsh-webhook | 飞书机器人、桌面通知、webhook |
| Agent/编排 | dsh-workflow、dsh-deep-research、dsh-data-agent、dsh-browser4 | 工作流层、深度研究、数据库分析、浏览器自动化 |
| 记忆/监控 | dsh-mnemon、dsh-whale-report、dsh-usage-stats | 三层记忆、会话报告、用量统计 |
| 开发基建 | plugin-template、dsh-plugin-check、dsh-toolkit、fabric | 插件模板、健康检查门禁、零依赖工具包、hook 处理器 |

---

## 3. 功能借鉴（用在哪、什么时候做）

### 3.1 DSH-better-sidebar → Phase 2 文献页（高优先）

- **是什么**：服务化侧边栏框架。任何插件用 `ctx.betterSidebar.registerTab()` /
  `registerFileViewer()` 注册新页面/预览器；内置 7 tab + 6 viewer（文件树、Git、
  终端、内嵌浏览器、PDF/Markdown/HTML 预览、后台任务页）与三方插件同 API 对等。
- **怎么用**：Phase 2 的【文献】页可作为 better-sidebar 的一个 tab，直接复用它的
  PDF/HTML/Markdown 预览渲染精读页与浅读笔记，减少自研 UI 工作量；
  相比 `conversation.view` 标签，better-sidebar 更接近 Zotero 主窗口体验（可拖分栏、
  会话隔离、按需加载 325KB）。
- **何时**：Phase 2 开工时先做小 demo 对比 `conversation.view` vs `better-sidebar`，
  再定实现路径（当前倾向 better-sidebar）。
- **参考**：`docs/external-plugin-guide.md`（接入指南）、`src/client/builtins/`（参考实现）。

### 3.2 dsh-lark → Phase 3 飞书授权（中优先）

- **是什么**：把 DSH 接进飞书聊天的渠道插件。
- **可借鉴**：扫码创建应用、免公网服务器、免回调地址的授权模式——
  比我们原方案（手动建自建应用拿 App ID/Secret）更顺滑，Phase 3 飞书同步可参考。
- **不照搬**：它做的是"飞书当聊天入口"，我们做的是"写飞书多维表格"，业务面不同。

### 3.3 dsh-browser4 → 可选：开放论文自动化（低优先）

- **是什么**：AI 原生浏览器引擎（自主 agent 用）。
- **可借鉴**：仅限**合法来源**（开放获取）的自动抓取研究；
  登录/验证码/MFA 仍必须由人完成（项目安全底线不变）。
- **何时**：Phase 3 之后视需要评估，不进入当前路线。

### 3.4 dsh-mnemon → 可选：笔记检索增强（低优先）

- **是什么**：三层记忆控制面（运行时上下文 / 可搜索项目文档 / 可插拔长期记忆）。
- **可借鉴**：我们的文献库全文搜索（FTS5）可借鉴其"文档检索 + 记忆路由"思路，
  但暂不引入新依赖。

---

## 4. 开发流程借鉴（优先级最高）

### 4.1 dsh-plugin-check → 插件健康检查门禁（高优先，近期做）

- **是什么**：只读扫描插件仓库，33 项检测：清单协议 / patch 格式 / 构建陷阱 /
  hub 收录状态，输出合规报告与修复建议（零依赖、不构建被检查仓库）。
- **可借鉴**：把社区踩坑（cordis 双副本、tsconfig 缺件、patch name 不一致、
  产物残留 `.ts` 运行时必崩）变成我们仓库的自动化门禁；
  **直接用**：装 `@deepseek-ai/dsh-plugin-check` 注册 `plugin_check` 工具，
  CI 或会话内对 `dsh-scientific-reading` 仓库跑一次。
- **何时**：下一步（Phase 1 收尾时）。

### 4.2 plugin-template → 生产级插件测试基建（高优先，Phase 2 前做）

- **是什么**：官方系插件开发模板，含 `.agents/skills/`（计划→脚手架→实现→测试→发布）、
  `patches/`（宿主补丁约定）、`tests/harness.ts`（真 Cordis 挂载测试）、
  vitest + tsdown、`AGENTS.md` 贡献规则、`verify-self-contained.mjs` 仓库边界检查。
- **可借鉴**：
  ① 补插件级自动化测试（harness 挂载 + 工具注册冒烟）——我们现在只有 tsc 编译；
  ② 采用 `patches/` 约定管理宿主补丁（未来需要时）；
  ③ 按 `src/config.ts / runtime.ts / index.ts` 分层组织源码；
  ④ 仓库边界校验脚本（防止产物/密钥/论文数据误入仓库）。
- **何时**：Phase 2 之前补齐。

### 4.3 CI 冒烟钉版（中优先）

- better-sidebar 的做法：CI 挂载冒烟并钉死 DSH 版本（如 `@deepseek-ai/dsh@0.1.0-rc.8`），
  peer/devDependencies 同步升版，lockfile 零旧版残留。
- 我们的 GitHub Actions 也应：锁 DSH 版本 + 装插件跑真实冒烟（加载 + 工具注册断言）。

---

## 5. 明确不借鉴

| 项 | 原因 |
|---|---|
| dsh-lark 的"飞书当聊天入口" | 我们只写飞书表格，不把飞书当控制台 |
| dsh-browser4 的自动化登录/绕过 | 违反项目安全底线（登录/MFA 必须人做） |
| dsh-tianshu-tui / dsh-tui | 终端 UI 与我们的 Web 文献页定位不同 |
| dsh-workflow / dsh-deep-research | 多 Agent 工作流编排，本项目是单 agent 顺序流水线，暂不需要 |
| dsh-genui 对话内 UI 组件 | 我们的产物是文档/HTML 页，不依赖对话内渲染 |

---

## 6. 落地计划（简表）

| # | 事项 | 优先级 | 时机 |
|---|---|---|---|
| 1 | 接入 dsh-plugin-check 做开发门禁 | 高 | Phase 1 收尾 |
| 2 | 按 plugin-template 补测试基建（harness + vitest + 边界校验） | 高 | Phase 2 前 |
| 3 | 文献页选型 demo：conversation.view vs better-sidebar | 高 | Phase 2 开工 |
| 4 | CI 冒烟 + 钉 DSH 版本 | 中 | 有 GitHub Actions 时 |
| 5 | 飞书授权借鉴 dsh-lark 扫码模式 | 中 | Phase 3 |
| 6 | 开放论文自动化（dsh-browser4，仅合法来源） | 低 | 后置评估 |

---

## 7. 参考链接

- 组织主页：https://github.com/omdsh-dev
- DSH-better-sidebar：https://github.com/omdsh-dev/DSH-better-sidebar
- dsh-lark：https://github.com/omdsh-dev/dsh-lark
- dsh-plugin-check：https://github.com/omdsh-dev/dsh-plugin-check
- plugin-template：https://github.com/omdsh-dev/plugin-template
- dsh-browser4：https://github.com/omdsh-dev/dsh-browser4
- dsh-mnemon：https://github.com/omdsh-dev/dsh-mnemon
