# 全新 Windows 机器安装设计

## 目标

让只有 Codex 的 Windows 10/11 x64 机器，通过一段可复制的 PowerShell 流程完成以下工作：

1. 安装 Git、Node.js 22、Python 3.11 和 pnpm；
2. 安装已验证的 DeepSeek Harness `0.1.0-rc.7`；
3. 克隆并安装 Scientific Reading Python 引擎；
4. 克隆、构建并以真实 tarball 安装 DSH 插件；
5. 配置引擎路径、MinerU API 和可选飞书凭据；
6. 启动 `web` Profile，并通过配置 dump、HTTP 页面和插件入口完成最小自检。

## 安装边界

- README 以 PowerShell 为唯一主流程，不同时维护多套操作系统命令。
- DSH 固定为项目已实机验证的 `0.1.0-rc.7`；最新版只作为升级说明，不进入首次安装主路径。
- Node.js 固定 22，Python 固定 3.11；使用 `winget` 安装，安装后重新打开 PowerShell。
- 两个仓库放在用户可修改的源码目录；论文、SQLite、PDF、MinerU 资产和凭据继续保存在仓库外。
- Python 引擎使用独立 `.venv`，插件使用 `npm ci`、`build:ci` 和 `npm pack` 生成的 tarball安装。
- `SCIENTIFIC_READING_PYTHON`、`MINERU_API_TOKEN`、`FEISHU_APP_ID`、`FEISHU_APP_SECRET` 从启动 DSH 的宿主环境继承，不写入 Git。
- 飞书是可选配置；没有飞书凭据不阻止本地文献工作流启动。

## README 结构

现有“安装与启动”章节改为以下顺序：

1. **从零安装总览**：列出耗时、需要用户准备的账号或密钥，以及安装完成后的访问地址。
2. **安装基础依赖**：提供 `winget` 命令和版本检查命令。
3. **安装 DSH**：全局安装固定版本，初始化 `web` Profile并验证版本。
4. **安装引擎**：克隆仓库、创建虚拟环境、可编辑安装并执行 CLI 探活。
5. **安装插件**：克隆仓库、安装依赖、构建、打包、安装 tarball并 dump 配置。
6. **配置环境变量**：区分必需的引擎路径、精读所需 MinerU Token、可选飞书凭据；明确 `setx` 只对新进程生效。
7. **首次启动与界面配置**：启动 DSH、配置模型、选择工作区、检查“文献”入口。
8. **最小验收**：检查 DSH 版本、Profile 配置、HTTP 页面和插件加载，不发起真实 MinerU或飞书写入。
9. **更新、卸载与故障排查**：覆盖命令找不到、版本不符、插件未出现、引擎未找到和环境变量未生效。

## 后续检索路线记录

在路线图中增加一个未实现阶段，固定以下边界：

```text
研究问题
  -> AI 生成检索词与主题拆分
  -> OpenAlex / Semantic Scholar / PubMed / arXiv / Crossref / Zotero 适配器
  -> 标识符规范化、来源记录与去重
  -> 候选文献收件箱
  -> 用户加入待读或忽略
  -> 下载、MinerU API、reader、飞书
  -> 基于已读论文的引用网络继续发现
```

初版不整体嵌入 ARIS、ScholarQA 或其他大型框架；只借鉴多来源降级、查询重排和引用网络设计。AI 的相关性判断只影响排序，不自动触发 PDF 下载。

## 验证与发布

- 用 README 中的命令在干净临时目录逐项做无副作用语法和版本检查。
- 运行 Markdown 链接与命令静态检查、`git diff --check`，并确认 README 不包含真实凭据。
- 只提交本规格、README 和路线图改动，不纳入现有未跟踪文件。
- 使用中文提交信息，推送插件仓库 `main`。

