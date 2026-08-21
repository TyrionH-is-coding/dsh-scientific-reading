# Client 正式源码与确定性构建设计

## 1. 背景

插件当前只有手写的 `lib/client.js`。它既是人类编辑的源码，也是宿主加载的构建产物，因此无法可靠判断产物是否过期，也不适合继续扩展原生文献页。

本阶段只偿还这项工程债，不改变文献页布局、交互、路由、工具或设置字段。

## 2. 方案选择

考虑过三种方案：

1. 引入 esbuild、tsdown 等 bundler；能支持模块化和 TypeScript，但新增依赖与 DSH lazy-CJS 包装配置，超出本阶段需要。
2. 用 TypeScript 编译浏览器代码后再自定义包装；类型收益有限，仍需维护额外包装器。
3. 保留已验证的 lazy-CJS 浏览器格式，将其移到规范源文件，并由无依赖 Node 脚本确定性生成 `lib/client.js`。

采用方案 3。它不改变运行时格式，不新增 npm 依赖，并能立即建立单一源码与新鲜度门禁。未来需要组件拆分时，再在这个稳定边界上评估 bundler。

## 3. 文件职责

- `client/client.js`：唯一允许人工维护的客户端规范源码，内容保持当前 lazy-CJS 模块格式。
- `scripts/build-client.mjs`：读取规范源码，规范化为 UTF-8/LF，并原子生成 `lib/client.js`；支持 `--check` 只读比较。
- `tests/client-build.mjs`：在临时目录验证生成可复现，以及 `--check` 能识别过期产物。
- `scripts/plugin-check.mjs`：调用同一比较逻辑，拒绝缺失或过期的 client 产物。
- `package.json`：提供 `build:client` 与 `check:client`，并让正式 `build` 同时执行 host 编译和 client 构建。
- `scripts/build.sh`：完成 TypeScript 编译后运行 client 构建脚本。

## 4. 数据流

```text
client/client.js
    │ node scripts/build-client.mjs
    ▼
lib/client.js ── DSH 通过 package exports ./client 加载

client/client.js + lib/client.js
    │ node scripts/build-client.mjs --check
    ▼
一致：退出 0；不一致或缺失：退出 1
```

构建脚本不得读取用户数据目录、网络或 DSH 配置。生成结果只取决于规范源文件字节与固定的换行规则。

## 5. 错误与边界

- 规范源文件缺失：构建与检查都失败并给出相对路径。
- 产物缺失：普通构建创建；`--check` 失败。
- 产物内容过期：普通构建覆盖；`--check` 失败。
- 写入使用同目录临时文件后 rename，避免生成半截产物。
- 不添加 watcher、压缩、source map、React 重写或 UI 重构。
- 不触碰 Python 引擎、飞书配置和仓库外论文资产。

## 6. 测试与验收

1. 测试先证明当前仓库没有可调用的 client 构建器。
2. 构建两次得到完全相同的 `lib/client.js`。
3. 人为修改临时产物后，`--check` 必须失败；重新构建后再次通过。
4. `plugin-check` 对规范源与产物做内容级比较，不再只检查 `lib/client.js` 是否存在。
5. `tests/harness.mjs`、`tests/feishu-env-only.mjs`、`scripts/plugin-check.mjs` 与 `scripts/verify-live.mjs` 全部通过。
6. `lib/client.js` 的运行内容保持不变，文献页与设置卡片行为不变。

