# 第三方组件声明

本项目直接使用以下运行时组件：

- Beautiful Soup 4 — MIT License
- latex2mathml — MIT License
- Pillow — HPND License
- openpyxl — MIT License
- tinycss2 — BSD-3-Clause，Copyright (c) 2013-2020, Simon Sapin and contributors；用于解析 Reader 自定义 CSS。许可证随安装的官方 wheel 分发。
- webencodings — BSD-3-Clause，Copyright (c) 2012, Simon Sapin；tinycss2 的编码依赖。许可证随安装的官方 wheel 分发。
- DeepSeek Harness 相关 npm 包 — 以各包随附许可证为准
- Cordis 与 Schemastery — MIT License

MinerU 通过官方 HTTP API 调用，不作为本仓库依赖或二进制再分发。
本项目不再依赖或分发 PyMuPDF、Zotero 插件或 MinerU 本地 CLI。

OA 模块采用 [ScanSci PDF 1.9.0](https://pypi.org/project/scansci-pdf/1.9.0/)（Apache-2.0）的 arXiv/Unpaywall HTTP 来源及网络/PDF辅助函数；Europe PMC 仅接受明确 OA 的全文链接。固定 wrapper 不初始化综合来源注册，不调用机构或浏览器路线。官方 wheel SHA-256 为 `77377292bb197ee1dac8d6597b09d4e46a4a21b41b98245cb3136b347f45aee7`。

Requests、urllib3、certifi、charset-normalizer、idna、PySocks 及 Beautiful Soup 闭包均由 `scripts/oa-requirements.txt` 固定官方 wheel 与 SHA，许可证随各 wheel 分发。这里安装的是固定 OA 入口所需闭包，不宣称完整 ScanSci CLI/MCP/Web 环境；机构、浏览器和其他未使用 extras 不安装。
