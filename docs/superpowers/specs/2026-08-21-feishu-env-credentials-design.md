# 飞书凭证仅使用宿主环境变量：设计说明

## 背景

当前插件同时存在两套互相矛盾的说法：设置卡片把 `feishuAppId`、`feishuAppSecret` 标成“未启用”，但 `engineFeishuSync()` 实际会优先把这两个设置值注入子进程。这样既可能让凭证落入 DSH 设置文件，也使使用手册无法准确描述真正生效的来源。

## 已确认决策

飞书凭证的唯一来源是启动 DSH 宿主进程时已有的环境变量：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

插件配置文件只保存非敏感路径和行为设置；`feishu-config-v1` 继续只保存 `app_token`、`table_id` 与 `field_map`，且必须位于仓库外。插件不得从设置卡片、配置 JSON、日志、预览或 job 状态读取或输出飞书凭证。

## 最小改动

1. 从 TypeScript `Config` 接口与 schema 删除 `feishuAppId`、`feishuAppSecret`。
2. `engineFeishuSync()` 不再构造覆盖环境；沿用 `runCommand()` 对宿主 `process.env` 的继承，让引擎及其 worker 自然继承凭证。
3. 从设置卡片删除两个凭证输入框，避免误导或意外持久化。
4. 将现有手写客户端 bundle 纳入 Git 跟踪。它目前是插件唯一客户端实现，构建脚本不会从 `src/` 重新生成；若继续忽略，干净克隆后设置卡片无法复现。
5. 修正文档，明确设置顺序：设置宿主环境变量、重启 DSH、先 preview、逐篇确认后 sync。

## 安全与行为边界

- `sr_feishu_preview` 保持零网络、无需凭证。
- `sr_feishu_sync` 继续要求 `confirm=true`，引擎继续使用 `--confirm-write`。
- DOI → PMID → Zotero Key 查重、歧义停止和写后读回逻辑不变。
- 测试只使用虚构哨兵字符串，不接触真实凭证、不访问飞书、不产生远端写入。

## 验收标准

- schema 与客户端均不再出现两个凭证设置字段。
- 即使调用方在运行时对象中伪造旧设置字段，同步子进程看到的仍是宿主环境变量。
- preview/sync 工具注册及原有插件挂载测试不回退。
- TypeScript 类型检查、凭证来源回归测试、插件挂载测试和健康门禁全部通过。

