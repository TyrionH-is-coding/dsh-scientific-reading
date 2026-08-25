# 期刊正文优先阅读器生产迁移实施计划

> 执行范围：`Scientific-Reading-for-Newbies` 的生产 `reader.html` 生成器；插件仓库只保存本计划与验收记录。

**目标：** 将已经通过四档浏览器验收的“期刊正文优先”设计直接实现到生产生成器，删除旧卡片式首屏语义，同时保留离线、溯源、重点、图表放大和阅读位置恢复能力。

**边界：** 不改变翻译、重点和导览 JSON 合同；不引入运行时 DOM 重排覆盖层；不触碰 3080 Persistent Profile；不真实写飞书或触发机构认证。

**技术路线：** 在 `reader/build_reader.py` 中直接生成最终 DOM，并以单一生产 CSS/交互脚本提供桌面与移动端行为。以 BeautifulSoup DOM 断言固定结构，以浏览器四档实机检查固定视觉与交互。

---

## 任务 1：先固定生产 DOM 合同

**文件：**
- 修改：`tests/test_reader_v2.py`
- 修改：`tests/test_reader_interactions.py`

1. 增加断言：`body.periodical-first`，且初始语言为 `zh`、阅读模式为 `full`。
2. 增加断言：左栏中导读位于目录之前；导读跳转链接是折叠详情的兄弟节点，可独立点击。
3. 增加断言：工具条只包含目录、语言双态和阅读三态控件；不再输出旧状态胶囊与旧按钮。
4. 增加断言：题名、元数据、摘要直接进入首屏；不输出 `paper-kicker`、`paper-facts` 和正文内导读卡片。
5. 增加断言：脚本不使用 `toolbar.innerHTML`、`guide.cloneNode` 或运行时搬移正文导读。

**验证：** 新断言在旧实现上失败，形成可复现红灯。

## 任务 2：直接生成期刊正文优先 DOM

**文件：**
- 修改：`reader/build_reader.py`

1. 将四类导读构造成紧凑的左栏折叠列表；每条摘要和“定位原文”链接都保留 source block。
2. 在生成期构造桌面左栏与移动端目录抽屉，不依赖加载后复制或重排 DOM。
3. 直接输出精简工具条：目录、中文/中英、全文/无标记/重点。
4. 删除旧首屏装饰、统计胶囊和正文导读网格，保留题名、原文题名、元数据与连续正文。
5. 为 body 写入稳定的初始语言和阅读模式状态。

**验证：** 任务 1 DOM 测试通过。

## 任务 3：收敛生产 CSS 与交互

**文件：**
- 修改：`reader/build_reader.py`

1. 用一份生产 CSS 实现 800px 正文、约 1020px 图表、260px 左栏和 1000px 以下移动抽屉。
2. 中文正文使用宋体类衬线栈，标题和 UI 使用黑体类无衬线栈；重点使用浅黄/浅蓝行内底纹与页边圆点。
3. 英文默认折叠；中文/中英控件统一展开或收起原文，并同步 `body.dataset.language`。
4. 全文/无标记/重点三态统一控制去色和重点筛选；保留目录点、相邻图表与标题上下文。
5. 保留图表单 dialog、Escape/焦点归还、阅读位置恢复、打印和离线约束。

**验证：** `tests/test_reader_v2.py`、`tests/test_reader_interactions.py` 和 Node 语法检查通过。

## 任务 4：更新构建身份与发布合同

**文件：**
- 修改：`reader/build_reader.py`
- 修改：`tests/test_full_read_service.py`
- 修改：`tests/test_reader_v2.py`

1. 将构建身份提升为 `reader-html-v2.2-periodical`。
2. 更新 manifest、revision 与幂等缓存的预期，不改变最终 reader SHA 校验规则。
3. 验证旧输入能够重新生成新 reader，旧资产和旧 reader 不被移动或删除。

**验证：** reader、renderer、service 定向测试全绿。

## 任务 5：全量与浏览器验收

1. 在隔离 data root、清空飞书凭证的环境中跑引擎全量测试。
2. 用本地虚构工科论文生成正式生产 reader。
3. 在 1440×900、1280×720、900×720、390×844 四档检查首屏、溢出、目录/导读、语言、阅读模式、图表弹窗和阅读位置恢复。
4. 确认控制台无错误、无远程资源、无横向溢出。
5. 本地合并两仓 main，在 main 重跑全量；通过后清理阶段 worktree/分支，不 push GitHub。

**最终验收：** 生产 reader 与已批准期刊正文优先合同一致，两仓 main 有可追溯中文提交，全量测试和实机浏览器证据齐全。
