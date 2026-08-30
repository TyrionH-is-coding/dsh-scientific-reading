# 论文“整理入库”子会话设计

## 目标

在 DSH 的“文献模式 → 文献”页为每篇论文提供【整理入库】入口。点击后创建或恢复一个真正的 DSH 持久子会话，AI 先提出候选关键结论，用户在子会话中讨论、修订并明确确认；只有确认后的结论才写入 SQLite，并由 SQLite 刷新到 Excel。

同一篇论文在不同父会话下必须有不同的整理子会话和结论。父会话是用户的第一层主题分类，例如“代谢学文献”和“免疫学文献”。论文 PDF、MinerU 产物和中英精读 HTML 仍是全局论文资产，不因父会话重复保存。

## 已验证的 DSH 宿主能力

目标宿主版本为 `0.1.0-rc.7`。对该版本源码和同组织插件的核对结果如下：

- `ctx.subagents.startContinuable()` 创建可继续、可冷恢复的持久子会话，并返回稳定 `childId`。
- 子会话头部持久包含 `parentSession`、`origin: 'subagent'`、`delegationDepth` 和继承的 `agentPreset`。
- 文献父会话使用 `scientific-reading` preset，因此子会话会继承文献工具和提示词组合。
- 子会话 descriptor 的 `label` 会成为子会话目录中的显示标题；这里直接使用论文标题。
- `origin: 'subagent'` 的会话不进入普通顶层会话列表。
- 客户端先调用 `sessions.refreshSubagents(parentSessionId)`，再调用 `sessions.openSubagent({ parentSessionId, childSessionId, mode: 'continuable' })` 即可打开子会话。
- `dsh-sidechain` 已证明持久侧会话和内嵌会话可由插件实现；`DSH-better-sidebar` 已证明可折叠子代理树和侧边会话可作为后续增强，但不作为首版前置条件。

因此首版不伪造聊天界面，也不直接操作 DSH 会话文件。插件只负责论文与会话绑定、文献页入口、整理提示、确认工具和文献资产入库。

## 用户流程

1. 用户只能在“文献模式 → 文献”页看到每篇论文的【整理入库】按钮。
2. 客户端读取当前父会话 ID，并向插件发送 `parent_session_id` 和 `paper_id`。
3. 插件按 `(parent_session_id, paper_id)` 查询 SQLite：
   - 已绑定：返回原 `review_session_id`；
   - 未绑定：创建一个 continuable 子会话，把论文标题作为 label，把整理任务和论文标识作为首条消息，再保存绑定。
4. 客户端刷新该父会话的子会话目录并打开返回的子会话。
5. AI 首轮读取论文上下文，列出候选关键结论及证据位置，明确标注“尚未入库”。
6. 用户与 AI 讨论、增删和修订。讨论文本属于 DSH 子会话历史，不自动等同于资产库事实。
7. 用户明确同意入库后，AI 调用确认工具。工具从当前执行上下文读取真实子会话 ID，校验其绑定关系后，原子写入 SQLite。
8. 写入成功后刷新 Excel；若 Excel 正被占用，SQLite 成功仍是事实，Excel 标记为待刷新并向用户说明。

## 会话与权限边界

绑定唯一键为：

```text
(parent_session_id, paper_id) -> review_session_id
```

- 同一父会话重复点击必须恢复同一子会话。
- 同一论文在不同父会话下得到不同子会话，并分别保存结论。
- 客户端提供的父会话必须是当前已列出的文献模式会话；服务端还必须能从 `ctx.agents` 找到对应的 live parent Agent，才允许创建新子会话。
- 论文必须已经存在于 SQLite，客户端传入的标题不作为事实来源。
- 子会话创建通过 DSH `fork` provider，继承父会话已完成历史作为参考，但首条边界提示明确本会话只负责指定论文。
- 整理工具以 `ToolRunContext.agent.id` 识别当前会话，不接受模型自行填写 `review_session_id`。
- 首版允许子会话继承文献模式工具；确认工具本身仍校验当前会话必须是已绑定的整理子会话。

## SQLite 事实模型

现有 `library.sqlite` 升级到 schema v3，新增两张表。

### `review_sessions`

| 字段 | 含义 |
| --- | --- |
| `parent_session_id` | 父 DSH 会话 ID |
| `paper_id` | 论文 ID，外键到 `items` |
| `review_session_id` | DSH 持久子会话 ID，唯一 |
| `created_at` | 首次绑定时间 |
| `updated_at` | 最近恢复或写入时间 |

主键为 `(parent_session_id, paper_id)`。

### `review_conclusions`

| 字段 | 含义 |
| --- | --- |
| `conclusion_id` | 稳定结论 ID |
| `parent_session_id` | 父会话分类 |
| `paper_id` | 论文 ID |
| `review_session_id` | 产生该结论的子会话 |
| `conclusion_type` | 简短类型，如“主要发现”“方法”“局限” |
| `conclusion_text` | 用户确认后的结论正文 |
| `evidence_locator` | 页码、章节、图表或原文定位；未知时为空字符串 |
| `confirmed_at` | 用户确认写入时间 |
| `created_at` | 记录创建时间 |
| `updated_at` | 最近更新时间 |

所有已确认结论都保留为独立行，不以论文或父会话覆盖旧结论。首版不把候选结论写入 SQLite；候选与讨论由 DSH 会话历史保存，避免把未确认内容混入长期事实源。

## HTTP 与工具合同

### 打开整理子会话

`POST /sr/api/reviews/open`

请求：

```json
{ "parent_session_id": "...", "paper_id": "library_..." }
```

响应：

```json
{
  "status": "created | reused",
  "parent_session_id": "...",
  "paper_id": "...",
  "review_session_id": "...",
  "mode": "continuable"
}
```

请求必须通过现有同源与 CSRF 写边界。服务端对同一绑定使用进程内单飞，避免连续双击创建两个子会话；SQLite 唯一约束是最终并发保护。

### 子会话工具

- `sr_review_context`：无参数；按当前子会话绑定读取论文元数据、Abstract、精读 HTML/Markdown 路径和已有确认结论，给 AI 形成候选结论。不得把不存在的内容补成事实。
- `sr_review_confirm`：接收非空 `conclusions` 数组，每项只有 `conclusion_type`、`conclusion_text`、`evidence_locator`；按当前子会话绑定写入所有条目，随后刷新 Excel。工具描述必须要求只有在用户明确确认后调用。

父会话后续的整体管理默认读取 SQLite 中的确认结论，而不是无边界地加载全部子会话 transcript。这样 Session ID 负责定位与溯源，SQLite 负责长期可查询事实。

## Excel

现有“文献”表继续保持一篇论文一行，不塞入可变数量的结论。新增“整理结论”表，一条已确认结论一行，列为：

```text
父会话 ID、论文标题、文献 ID、整理子会话 ID、结论类型、确认结论、证据位置、确认时间
```

该表由 SQLite 全量生成并设筛选、冻结首行和换行显示。它是派生快照，不从 Excel 回写结论；现有“文献”表的三个用户字段回写合同保持不变。

## 首版与后续增强

首版必须完成真正的 DSH 子会话、隐藏于普通列表、论文绑定、恢复、AI 首轮候选、显式确认、SQLite 和 Excel。首版不修改 DSH 核心，也不要求安装另一个插件。

后续可把这些子会话在侧边栏渲染为父会话下可展开/收回的二级树，并嵌入 transcript；实现可参考 `DSH-better-sidebar` 的 subagent topology 或 `dsh-sidechain` 的内嵌面板。该增强只改变呈现，不改变本设计的会话 ID、SQLite 绑定或结论事实模型。

## 验收

- 非文献模式和普通插件设置列表不存在【整理入库】入口。
- 文献模式每篇文献均有【整理入库】，且按钮可防止重复提交。
- 首次点击创建 `origin: subagent` 的 continuable 子会话，标题为论文标题；普通顶层列表不出现它。
- 同一父会话再次点击恢复相同子会话；不同父会话点击同一论文得到不同子会话。
- 子会话首轮主动提出候选结论，并明确尚未入库。
- 未调用确认工具前，SQLite 与 Excel 不出现候选结论。
- 明确确认后，多条结论全部进入 SQLite，并出现在 Excel“整理结论”表中。
- 工具不能为未绑定的普通会话写入结论，也不能通过伪造会话 ID 越权。
- Excel 被占用时不回滚 SQLite；状态明确显示待刷新。
- 现有文献下载、MinerU、精读 HTML、文献列表和三个 Excel 用户字段回写测试继续通过。
