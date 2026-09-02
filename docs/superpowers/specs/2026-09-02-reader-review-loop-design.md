# Reader 快速预览、审核与反馈闭环设计

## 决策摘要

为 `reader.html` 建立一条固定、可重复的开发审核闭环：Codex 修改 reader 后，复用本地缓存的解析、翻译和阅读资产，在数秒内生成候选 HTML，并通过固定本地地址打开统一审核页。用户直接查看修改前后、切换代表性论文和页面宽度，并使用 Codex 浏览器 Comment 指出问题。只有用户认可候选效果后，才运行多论文回归、浏览器验收、隔离 DSH 实机和必要的完整 MinerU API 链路。

第一版只服务 reader，不覆盖 DSH 文献库、设置页或其他插件界面。审核工具是开发依赖，不进入 npm 发布包，不增加普通用户安装体积，也不修改正式数据 generation。

## 目标

1. 从完成代码修改到用户看到候选 reader，典型耗时控制在 5–10 秒。
2. 快速循环不重新下载 PDF，不调用 MinerU API，不重新请求 LLM 翻译或校文。
3. 用户始终访问同一个本地审核入口，不需要寻找不同版本的 HTML 文件。
4. 审核页能快速比较修改前和修改后，并覆盖桌面、平板和手机宽度。
5. 用户可直接通过浏览器 Comment 反馈具体元素、截图和文字说明。
6. 用户认可后，再自动扩大到代表性论文、结构测试、浏览器 QA 和隔离 DSH 验收。
7. 快速审核、代表性验收和完整链路验收具有明确边界，避免每次小改动都运行最慢流程。

## 非目标

- 不在审核页内重新实现一套评论、截图或工单系统；反馈继续使用 Codex 浏览器 Comment。
- 不为第一版加入 reader 之外的 DSH 界面预览。
- 不将测试 PDF、完整版权论文、MinerU 原始 ZIP 或用户数据提交到 Git。
- 不引入 Playwright 浏览器下载、Electron 或常驻开发服务依赖。
- 不让快速预览覆盖正式 `reading/reader.html`、manifest 或 package manifest。
- 不替代发布前的真实 DSH 路由和必要的 MinerU API 验收。

## 用户工作流

### 1. 用户提出修改

用户可用文字、截图或浏览器 Comment 描述问题。Codex根据修改文件和影响面判断本轮属于：

- reader 样式或浏览器交互；
- renderer、文本合同或 reader 数据绑定；
- MinerU、任务状态或 DSH 路由集成。

该分类由 Codex完成，不要求用户选择测试模式。

### 2. Codex 修改并快速渲染

Codex 在隔离开发分支中修改代码，先运行本轮相关的最小测试，然后执行：

```powershell
npm run reader:review -- --paper-id <paper_id>
```

该命令：

1. 查找指定论文当前合法的活动 generation；
2. 只读加载现有 metadata、source map、translation、review、guide、highlight 和资产；
3. 把会话开始时的正式 reader 复制为 baseline；
4. 使用当前工作树代码把候选 reader 写入开发审核目录；
5. 原子刷新审核 manifest；
6. 启动或复用本机审核服务器；
7. 输出固定审核地址和结构化结果。

快速渲染不得调用下载、MinerU API、LLM、飞书或机构认证，也不得写回来源 generation。

### 3. 用户查看统一审核页

固定入口为：

```text
http://127.0.0.1:8895/review
```

Codex自动在应用内浏览器打开该地址。审核页顶部仅提供开发审核控件：

- 论文选择；
- 桌面、平板、手机宽度；
- 修改前、修改后；
- 当前构建时间和 commit；
- 结构测试状态。

正文在 iframe 中按所选宽度显示。切换 baseline/candidate 时尽量保留当前 hash、滚动比例和对应 block；候选 manifest 更新后自动刷新 iframe，不要求用户重新打开地址。

### 4. 用户提出修改意见

用户直接选中页面区域添加 Codex 浏览器 Comment，或继续发送文字和截图。浏览器 Comment 自带页面 URL、目标元素、视口和局部截图，审核页不重复保存反馈。

Codex收到反馈后修改代码、运行定向测试、重新执行 `reader:review`。用户在同一地址查看刷新后的候选版本。该循环可重复，直到用户明确认可当前效果。

### 5. 用户认可后扩大验收

用户说“可以”“这一版符合”或同义表达后，Codex执行：

```powershell
npm run reader:acceptance
```

该命令渲染全部代表性审核案例并运行 reader/renderer/interaction 定向测试。Codex随后用应用内浏览器完成桌面、平板和手机的真实交互与视觉 QA，并把结果写入审核 manifest，供审核页显示。

### 6. 合并前实机验收

代表性审核通过后，Codex根据影响面决定是否需要完整数据链：

- 仅 CSS、无数据语义的 reader 交互：不重复调用 MinerU API；
- renderer 或数据合同：使用本地 fixture 和可信缓存 generation 验证；
- MinerU、校文/翻译输入、generation 或任务状态：运行一次隔离的真实 MinerU API 链路。

随后执行：

```powershell
npm run acceptance:dsh
```

它构建真实 tarball、安装到隔离 DSH Profile、通过正式 `/sr/reading/<paper_id>` 路由打开候选 reader，并验证资源加载和关键交互。所有隔离验收通过前，不替换用户正在使用的持久 Profile。

### 7. 交付

最终报告保持简短，至少包括：

```text
本轮修改：<数量与摘要>
快速预览：通过/失败
代表性论文：通过/失败
移动端与交互：通过/失败
隔离 DSH：通过/失败
完整 MinerU 链路：已运行/按影响面无需运行
审核地址：http://127.0.0.1:8895/review
```

通过后再合并回 `main` 并运行 main 上相应全量测试。

## 架构

### 1. 审核会话目录

审核产物写入仓库外或 Git 忽略的临时目录，例如：

```text
<temp>/dsh-scientific-reading-review/
├─ session.json
├─ review-manifest.json
├─ baseline/
│  └─ <case>/reader.html
├─ candidate/
│  └─ <case>/reader.html
├─ assets/
└─ screenshots/
```

目录不得位于正式 data root 的 generation 中。退出审核或清理目录不会影响论文资产。

`session.json` 记录审核会话身份、仓库、基线 commit 和来源 generation 的只读身份。`review-manifest.json` 记录候选构建版本、案例状态、测试结果和浏览器 QA 摘要。所有写入采用临时文件后原子替换，审核页不会读到半成品。

### 2. 只读审核渲染器

新增开发 CLI 或脚本，把“加载已完成可信资产”和“发布正式 generation”分开。审核渲染器：

- 使用与生产 reader 相同的 `FullReadRenderer` 和 `build_reader`；
- 校验来源 generation、路径 containment 和必要 SHA；
- 输出到显式的审核目录；
- 禁止调用正式发布 hook；
- 禁止刷新正式 reader、reader manifest 或 package manifest；
- 禁止通过复制后修改的方式让测试误用陈旧资产。

若现有 renderer 不能在不发布的情况下输出候选文件，只增加一个窄的 preview 输出边界，不重构生产发布流程。

### 3. Baseline 与 candidate

首次建立审核会话时，将来源 generation 中已经验证的正式 reader 复制为 baseline。后续代码修改只刷新 candidate。baseline 在该会话中保持不变，直到用户明确开始新一轮审核。

审核页只切换两个静态、同源 iframe，不对生产 reader DOM 做运行时重写。candidate URL 带审核 revision，避免浏览器缓存旧内容。

### 4. 固定审核服务器

服务器只监听 `127.0.0.1:8895`，不绑定局域网地址。它只允许访问审核目录白名单中的 HTML、图片和 manifest，拒绝 `..`、绝对路径、符号链接逃逸和未知 MIME。

服务器通过所有者 PID/lock 文件识别自己的实例：

- 已有本项目审核服务时复用；
- 端口被其他程序占用时失败并给出明确说明，不杀死未知进程；
- Windows 子进程使用无窗口启动参数，不弹终端窗口；
- 提供显式停止命令，但正常重复渲染不重启服务器。

审核页轮询一个很小的 manifest revision；发现候选更新后保存 iframe 阅读位置、刷新并恢复位置，不需要文件系统 watcher 或 WebSocket。

### 5. 审核案例

第一版至少覆盖三类案例：

1. 公式与层级目录：多级标题、行内/块级公式、长英文正文、引用；
2. 角标与复杂文本：合法作者脚注、数字上下标、`fi` 误角标、缺失空格、双栏来源；
3. 图表与长图注：多图、多表、长图注、图表弹窗及邻近重点。

案例来源分两层：

- 本机真实案例：从用户现有完成 generation 只读加载，不复制到 Git；
- 仓库合成 fixture：只保留验证布局和合同所需的短文本、微型图片和结构化 JSON，用于 CI 和新机器，不包含完整论文或 PDF。

审核会话优先使用用户指定真实论文；`reader:acceptance` 同时运行合成 fixture，保证可重复性。

## 三个命令

### `npm run reader:review`

用途：开发循环中的快速候选渲染和审核服务启动。

最少参数：

```text
--paper-id <id>     指定本机真实论文
--case <name>       指定仓库合成案例
--new-session       丢弃旧 baseline，开始新审核会话
```

无参数时复用当前审核会话；没有会话时给出可用案例，不猜测论文。

成功输出 JSON 摘要和固定 URL。典型目标 5–10 秒，不以绝对超时掩盖慢操作；manifest记录各阶段耗时用于后续优化。

### `npm run reader:acceptance`

用途：用户认可候选后的代表性回归。

执行：

- 所有合成 fixture 渲染；
- 当前审核会话中的真实案例渲染；
- reader、renderer、数据合同和静态交互测试；
- HTML结构、资源、公式、目录、重点、响应式与横向溢出前置检查；
- 生成等待 Codex 浏览器 QA 的清单。

该命令不调用 MinerU API 和 LLM。

### `npm run acceptance:dsh`

用途：合并前的真实插件包装和隔离 DSH 验收。

执行：

- 构建 wheel、TypeScript、client 和 tarball；
- 安装到临时 Profile；
- 使用临时 data root；
- 启动隔离 DSH；
- 验证正式阅读路由、资源和 HTTP 安全边界；
- 结束时关闭仅由本命令创建的进程并保留失败证据。

它不得触碰持久 Profile、真实飞书或机构认证。

## 审核页设计

审核页采用简洁工具栏，不改变候选 reader 本身：

```text
[案例 ▼] [修改前 | 修改后] [桌面 | 平板 | 手机]
构建 cdf9ced · 14:32:08    结构测试 24/24
```

- 桌面、平板、手机分别模拟固定内容宽度；真实浏览器验收仍使用对应 viewport。
- 默认打开 candidate。
- baseline/candidate 切换不重置所选案例和视口。
- 测试失败时只显示数量和简短摘要，详细日志保存在 manifest/终端，不遮挡 reader。
- 审核页不注入生产功能，也不把审核工具栏打包进最终 `reader.html`。

## 测试分层

### 快速门

每次反馈循环只运行被修改组件的最小测试，并渲染当前案例。失败时不向用户宣称“可看成品”，但仍可在审核页保留最后一个成功候选并明确标记陈旧。

### 代表性门

用户认可视觉方向后运行全部 reader 相关测试和三类案例。Codex浏览器 QA 至少验证：

- 桌面、平板、手机布局；
- 无横向溢出；
- 目录折叠和跳转；
- 中英文与翻译展开；
- 全文、无标记和重点模式；
- 公式、角标、图注和图表弹窗；
- 个人荧光笔的创建、刷新恢复、换色和删除；
- 低价值区域折叠与恢复。

### 发布门

隔离 DSH 通过后，才允许合并。是否运行真实 MinerU API 由影响面决定，并在最终报告明确说明，不把“未运行”写成“通过”。

## 错误与恢复

- 来源 generation 不完整或 SHA 不匹配：拒绝快速渲染，不绕过完整性校验。
- baseline 不存在：要求新建审核会话，不把当前候选冒充 baseline。
- candidate 构建失败：保留上一个成功候选并在审核页显示 stale/failed。
- 审核服务器意外退出：下一次 `reader:review` 可重启；不会丢失 baseline/candidate。
- 浏览器缓存旧页面：candidate URL 使用 manifest revision；禁止依赖用户手动强刷。
- Comment 指向旧 revision：Codex先核对 URL revision，再决定复现或声明已被后续版本覆盖。
- 临时目录被删除：重新建立审核会话，不影响正式论文数据。

## 性能与包体约束

- 快速路径不调用外部网络、MinerU API 或 LLM。
- 审核服务器不使用热更新框架，不增加生产依赖。
- 仓库合成 fixture 总体保持小型，微型图片优先；测试 PDF 不进入发布 tarball。
- 审核脚本和 fixture 从 npm `files` 白名单中排除。
- 记录 source load、render、write、test 各阶段耗时；只有取得数据后才进一步优化。

## 验收标准

1. 修改 reader CSS 后，使用缓存案例能在目标 5–10 秒内看到 candidate。
2. baseline 与 candidate 可即时切换，且 baseline 在会话内不被覆盖。
3. 重复运行 `reader:review` 复用同一服务器和固定 URL，不产生重复后台进程。
4. 预览过程不会改变正式 reader、manifest、package manifest 或来源资产 SHA。
5. 候选更新后审核页自动刷新并尽量恢复阅读位置。
6. 三种宽度和三个代表性案例可切换，无审核控件泄漏到候选 reader。
7. 浏览器 Comment 可准确指向当前 candidate 元素，后续迭代继续使用同一审核入口。
8. `reader:acceptance` 不联网、不调用 MinerU API/LLM，并生成明确的浏览器 QA 清单。
9. `acceptance:dsh` 使用真实 tarball、隔离 Profile 和临时 data root，不触碰持久环境。
10. 审核工具、fixture和临时资产不进入发布包。
11. 端口冲突、候选构建失败、来源损坏和服务器重启均有明确、非破坏性恢复行为。
12. 最终报告明确区分已通过的层级与因影响面无需运行的层级。

## 实施边界

- 当前 `main` 存在其他在途修改；实现必须使用隔离 worktree，并在开始前明确基线与所有权。
- 第一版只增加 reader 审核闭环，不顺带重构 DSH UI、下载、MinerU provider 或论文管理。
- 应优先复用现有 renderer、reader 测试、应用内浏览器和 DSH 隔离验收能力。
- 不为测试便利降低 generation、路径或 SHA 的生产安全边界。
