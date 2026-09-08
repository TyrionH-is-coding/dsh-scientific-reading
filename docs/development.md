# 开发与验证

[项目首页](../README.md) · [使用指南](getting-started.md) · [技术设计](design.md)

## 从源码构建

需要 Node.js 22、Python 3.11 和 Git。运行目录与文献数据目录分别管理。

~~~sh
git clone https://github.com/TyrionH-is-coding/deep-literature-for-dsh.git
cd deep-literature-for-dsh
npm ci --ignore-scripts --legacy-peer-deps
python -m venv engine/.venv
~~~

激活该虚拟环境后执行（Windows 可使用 `engine/.venv/Scripts/python.exe`，macOS/Linux 使用 `engine/.venv/bin/python`）：

~~~sh
python -m pip install -e "engine[dev]"
npm run build:ci
npm pack --ignore-scripts
~~~

明确将 `PYTHON` 或 `SCIENTIFIC_READING_PYTHON` 指向该环境，可避免构建脚本选中其他 Python。生成的插件包名继续保留 `@dsh-external/dsh-scientific-reading`，安装方法见[使用指南](getting-started.md#安装与启动)。

构建从独立暂存目录生成 Python wheel，不能使用旧 `engine/build` 代替当前源码。前端只编辑 `client/client.js`，再运行 `npm run build:client` 更新受版本管理的 `lib/client.js`。

## 回归验证

使用临时数据根和合成夹具，先清除测试进程中的真实 MinerU 凭据：

~~~sh
npm run typecheck
npm test
npm run verify:restart-recovery
~~~

`npm test` 包括构建、Python 引擎、插件离线合同和资源检查，也会核验 wheel 与源码一致。它不代替真实模型、MinerU、浏览器或 Excel GUI 验收。

## 快速审核 Reader

无需重复下载、解析或翻译，直接读取离线夹具或已有 generation：

~~~sh
npm run reader:review -- --case formula-outline --new-session
npm run reader:review
~~~

浏览器打开返回的审核地址（默认 `http://127.0.0.1:8895/review`）。首次固定 baseline，后续生成 candidate，不改写原始阅读资产。

查看本机既有论文时：

~~~sh
npm run reader:review -- --paper-id doi_10.48550_arxiv.1706.03762 --data-root "/绝对路径/文献数据目录" --new-session
~~~

确认视觉效果后：

~~~sh
npm run reader:acceptance
npm run acceptance:dsh
~~~

第一层运行离线夹具和结构检查；第二层使用实际 tarball、临时 DSH Profile 和随机回环端口核验正式路由，不使用用户的持久文献库。找不到本机 DSH 时明确失败，不自动联网安装。

完成后停止本次审核服务：

~~~sh
npm run reader:review -- --stop
~~~

## 发布约定

- 固定来源提交，确认同一 SHA 的 CI；保留已公开附件，不以重打包覆盖旧版本。
- 核对 tarball、内置 wheel、来源清单和最终附件 SHA。
- 主线中的功能与已公开包的范围分别描述；真实账号和原生应用操作单列证据。
- 新版先发布文献插件，再发布引用该固定包的 Codex 工作台。
- 发布核对见[当前记录](release-readiness.md)；`docs/releases/v0.1.0/` 中的早期候选记录作为历史证据保留。
