# 期刊正文优先阅读器演示页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 `reader-v21-demo/reader.html` 改成首屏进入摘要、正文视觉优先且保留全部既有交互的期刊式演示页。

**Architecture:** 不重新生成演示数据，也不改 guide/highlight 合同。用一组作用域为
`body.periodical-first` 的 CSS 覆盖现有 v2 样式，并在现有 IIFE 初始化阶段重排导读和工具条 DOM；这样
可以快速验证视觉方向，同时保留 source block、图表 dialog、阅读位置和重点过滤逻辑。生产构建器迁移
是后续独立计划，本计划只交付可审核的演示页。

**Tech Stack:** 静态 HTML、原生 CSS、原生 JavaScript、Node.js 内置断言、Codex in-app Browser。

**执行状态（2026-08-25）：** Task 1–4 已完成。后续修订已统一学术字体体系（标题黑体、
正文宋体系、西文 Times），为局限性与参考文献补充 `focus-heading`，并在图表 dialog 打开时
暂停保存阅读位置。四档真实浏览器验收确认首屏、响应式、交互、离线与恢复行为符合合同；
验收中发现并修复语言状态未写入 `body.dataset`、导读跳转藏入折叠详情两项偏差。

---

### Task 1: 建立期刊式结构合同

**Files:**
- Create: `D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs`
- Test: `D:\Vibe Coding\reader-v21-demo\reader.html`

- [x] **Step 1: 写入失败的静态合同测试**

```js
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("./reader.html", import.meta.url), "utf8");

assert.match(html, /body\.periodical-first/);
assert.match(html, /class="control-group language-control"/);
assert.match(html, /data-language="zh"/);
assert.match(html, /data-language="bilingual"/);
assert.match(html, /class="control-group reading-control"/);
assert.match(html, /data-reading="full"/);
assert.match(html, /data-reading="clean"/);
assert.match(html, /data-reading="focus"/);
assert.match(html, /sidebar-guide/);
assert.match(html, /periodical-first-ready/);
```

- [x] **Step 2: 运行测试并确认旧演示页失败**

Run:

```powershell
node "D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs"
```

Expected: FAIL，第一条失败为缺少 `body.periodical-first` 或新的控制组。

### Task 2: 重排辅助信息与控制器

**Files:**
- Modify: `D:\Vibe Coding\reader-v21-demo\reader.html`
- Test: `D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs`

- [x] **Step 1: 在现有 IIFE 顶部重排 DOM**

在查询按钮之前执行以下确定性转换：

```js
const body = document.body;
body.classList.add('periodical-first');

const sidebar = document.querySelector('.reader-sidebar');
const toc = sidebar.querySelector('.toc');
const guide = document.querySelector('.reading-guide');
guide.classList.add('sidebar-guide');
guide.querySelector('.guide-heading').textContent = '导读';

for (const card of guide.querySelectorAll('.guide-card')) {
  const title = card.querySelector('h2').textContent.trim();
  const firstEntry = card.querySelector('.guide-entry');
  const firstSource = firstEntry.querySelector('.guide-source');
  const row = document.createElement('section');
  row.className = 'sidebar-guide-item';
  const details = document.createElement('details');
  details.innerHTML = `<summary><strong>${title}</strong><span>${firstEntry.querySelector('p').textContent.trim()}</span></summary>`;
  const content = document.createElement('div');
  content.className = 'sidebar-guide-content';
  content.append(...card.querySelector('.guide-list').children);
  details.append(content);
  const jump = firstSource.cloneNode(true);
  jump.className = 'sidebar-guide-jump';
  jump.textContent = '跳到正文';
  row.append(details, jump);
  card.replaceWith(row);
}
guide.querySelector('.guide-grid').className = 'sidebar-guide-list';
sidebar.insertBefore(guide, toc);
```

实现时不得使用 `innerHTML` 插入 guide 文本；上例的 summary 应改成 `createElement` + `textContent`，
保证演示实现与生产安全边界一致。

- [x] **Step 2: 将工具条收缩为三个控制组**

使用不包含数据插值的固定 HTML 字符串构造；该字符串只包含阅读器自身按钮，不接触题录、导读或
论文文本：

```html
<button id="toggle-sidebar" aria-expanded="true">目录</button>
<div class="control-group language-control" aria-label="语言">
  <button data-language="zh" aria-pressed="true">中文</button>
  <button data-language="bilingual" aria-pressed="false">中英</button>
</div>
<div class="control-group reading-control" aria-label="阅读模式">
  <button data-reading="full" aria-pressed="true">全文</button>
  <button data-reading="clean" aria-pressed="false">无标记</button>
  <button data-reading="focus" aria-pressed="false">重点</button>
</div>
```

将“回到上次位置”按钮移动到侧栏底部，禁用时通过 `hidden` 隐藏；删除工具条中的状态 chip 和计数。

- [x] **Step 3: 用状态函数替换三个旧开关监听器**

```js
const setLanguage = (mode) => {
  body.dataset.language = mode;
  sourceDetails.forEach((source) => { source.open = mode === 'bilingual'; });
  languageButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.language === mode));
  });
};

const setReadingMode = (mode) => {
  body.dataset.reading = mode;
  body.classList.toggle('highlights-off', mode === 'clean');
  article.classList.toggle('focus-only', mode === 'focus');
  readingButtons.forEach((button) => {
    button.setAttribute('aria-pressed', String(button.dataset.reading === mode));
  });
};
```

初始调用 `setLanguage('zh')` 和 `setReadingMode('full')`。保留 sidebar、progress、localStorage、TOC、
dialog 的既有处理。

- [x] **Step 4: 给重点标签增加非视觉可访问名称**

```js
for (const label of document.querySelectorAll('.highlight-label')) {
  label.dataset.label = label.textContent.trim();
  label.setAttribute('role', 'note');
  label.setAttribute('tabindex', '0');
  label.setAttribute('aria-label', label.dataset.label);
}
```

- [x] **Step 5: 运行静态合同测试**

Run:

```powershell
node "D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs"
```

Expected: PASS，无输出且退出码为 0。

### Task 3: 应用期刊正文优先视觉层

**Files:**
- Modify: `D:\Vibe Coding\reader-v21-demo\reader.html`
- Test: `D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs`

- [x] **Step 1: 添加作用域 CSS token 与阅读画布**

```css
body.periodical-first {
  --canvas: #f2efe7;
  --paper: #fffdf8;
  --text-column: 800px;
  --asset-column: 1020px;
  background: var(--canvas);
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", serif;
}
body.periodical-first .paper-card {
  overflow: visible;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}
body.periodical-first .paper-hero,
body.periodical-first article > :not(.paper-asset) {
  width: min(var(--text-column), calc(100% - 48px));
  margin-right: auto;
  margin-left: auto;
}
body.periodical-first article > .paper-asset {
  width: min(var(--asset-column), calc(100% - 24px));
  margin-right: auto;
  margin-left: auto;
}
```

- [x] **Step 2: 收紧题录并让摘要进入首屏**

隐藏 `.paper-kicker`、`.paper-facts`；移除 hero 背景装饰；题目使用 38–42px、`1.25` 行高；题录改成
横向自然换行；hero 底部与 article 顶部总留白不超过 54px。不得隐藏摘要或改变 article 顺序。

- [x] **Step 3: 样式化侧栏导读与三组控制器**

侧栏导读使用无卡片的一行预览、细分隔线和独立“跳到正文”链接；工具条使用透明背景分段按钮，
激活态只用深绿文字、浅绿底和 1px 边框。移动端保持相同状态标签，不显示旧 chip。

- [x] **Step 4: 降低重点和英文入口的视觉噪声**

重点底色作用于正文文本，不给 `.reading-block` 添加卡片边框；`.highlight-label` 缩成页边 8px 点，
hover/focus 时用 `data-label` 显示提示。`details.source-text > summary` 改为段末小型 `EN 原文` 入口，
英文展开后使用细左线，不加卡片背景。

- [x] **Step 5: 加入运行完成标记并复跑合同**

初始化结束时执行：

```js
body.classList.add('periodical-first-ready');
```

Run:

```powershell
node "D:\Vibe Coding\reader-v21-demo\verify_periodical_layout.mjs"
```

Expected: PASS。

### Task 4: 浏览器交互与视觉验收

**Files:**
- Verify: `D:\Vibe Coding\reader-v21-demo\reader.html`

- [x] **Step 1: 在现有本地服务器重新加载演示页**

Open: `http://127.0.0.1:8765/reader.html?v=periodical-first`

Expected: 页面标题和摘要在首屏，正文主流中没有导读卡片墙。

- [x] **Step 2: 检查四个 viewport**

依次检查 1440×900、1280×720、900×720、390×844。桌面首屏必须出现摘要文本；900×720 至少出现
“摘要”标题；390×844 允许题录换行，但导读不得插回正文。

- [x] **Step 3: 检查交互矩阵**

验证目录展开/收起、中文/中英、全文/无标记/重点、导读跳转、英文列表合并、Figure/Table dialog、
URL hash 和阅读位置恢复。每次切换只改变对应状态，不产生控制器互相覆盖。

- [x] **Step 4: 检查离线和控制台**

确认页面没有 HTTP(S) 请求、没有 console error、关闭 dialog 后焦点返回触发元素。

- [x] **Step 5: 记录交付边界**

交付演示页、合同脚本和浏览器验收结果。明确生产构建器尚未迁移，后续迁移必须复用本演示页的
DOM 语义、视觉 token 和交互状态，不重新设计。

**浏览器验收记录（2026-08-25）：**

- 1440×900、1280×720：摘要正文首段顶边均为 351px，可在首屏阅读；
- 900×720：摘要标题顶边 314px，侧栏切换为顶部抽屉；
- 390×844：摘要标题顶边 363px，工具条单行 45px，无横向溢出；
- 中英模式展开 9/9 个英文组，全文/无标记/重点状态可逆，导读 hash、图表 dialog、焦点归还、
  阅读位置自动恢复均通过；页面无 HTTP(S) 资源，控制台无 warning/error。
