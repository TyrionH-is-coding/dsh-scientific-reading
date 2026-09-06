# 0.1.0-rc.1 验收摘要

2026-09-06，两套产品已完成发布候选工程验收。本文公开检查结果和范围；原始日志、研究 PDF、用户库、账号状态及本机路径不随源码公开。源码推送与发布 GitHub Release 是分别执行的步骤。

| 对象 | 结果 |
| --- | --- |
| A 原生插件 | 最终 `npm test` 通过，Python 386 passed、1 skipped，全部 offline 和 4 项 assets 通过；独立托管 venv 的实际初始化、OA probe 和 CLI 通过 |
| A 包一致性 | tarball 57 文件和 wheel 中 49 个 Python 源文件完成文件集合与字节比对 |
| B 隔离工作台 | 37 项单元回归，12 项真实安装/隔离，23 项真实分类交接和手动 PDF 续接，10 项崩溃/正常关闭恢复，9 项升级回滚，30 项卸载保留数据检查通过 |
| B 内置浏览器 | 实例身份、原生 DSH、独立 OAuth 未登录状态实际读取成功；新用户文库保持为空 |
| Excel | 相同最终 A 模块在真实库独立副本上 29 项通过，固定 29 列/5 个 sheet/3 个用户写回字段，覆盖身份冲突暂存与修正后续接；未打开 Excel GUI |
| Codex OAuth 组件 | 当前源码 31 项回归通过，冻结候选阶段的真实官方 CLI 未登录协议通过；本地验收 provider 完成了真实 DSH 工具回合，不能代替本人 OAuth 模型推理验收 |

冻结的已验收附件身份：

- A `dsh-external-dsh-scientific-reading-0.1.0-rc.1.tgz`：`15f752f359ed2865a32671e1c7e0240bb74ad22033b706029efcbc7110672c59`。
- B `codex-scientific-reading-0.1.0-rc.1-win-x64.zip`：`f49d07bbba15446ef728a4541febf5610893b6932bf0e98ba390328bfe844a54`。
- B 安装程序快照：`2b6ebcc81a86b9d355e06f9928e5383816b392d16fe207c695af95bad0165739`。

环境为 Windows x64、实际 PowerShell 5.1，私有 Node 22.22.2、Python 3.11.16、DSH 0.1.0-rc.7、Codex CLI 0.146.0。B 的 npm 与 Python wheel 依赖锁定；A 的通用 Python 依赖仍使用声明的版本范围。

## 未覆盖的范围

本人 OAuth 登录后的真实多轮推理、额度返回和刷新，最终组合中新上传 PDF 的真实 MinerU 服务调用，Excel GUI，以及每家机构/出版社的访问可用性尚未全部验证。未取得正文时应保留待补 PDF；已保存 Key 不能作为解析成功的证据。

真实 R1 样本的公式控制词、引用续段、重复页眉和字符显示缺陷已修复并实际核对浏览器；原 OCR 的部分数字、DOI 和图注分段仍有明确限制。该样本仍为非正式工程预览，没有替用户确认读完，也没有声称译文和科学结论已全面验收。

旧 tag `v0.1.0-rc.1` 指向 CI 失败的 `a0db7cf8eba434c493ac2cb5e3d3d22ad403ab7a`，对应 Release 已撤回为草稿。修复提交 `401e98256d42e10650b5ec71a475634c1aedfd1b` 的[完整 GitHub CI](https://github.com/TyrionH-is-coding/dsh-scientific-reading/actions/runs/34013006939)通过，包含引擎 388 项、离线和资产测试；该结果不代表旧 tag 已修正，也不替代上表未覆盖的本人及外部服务验收。后续提交须核验其自身 CI，放行状态见[发布修复记录](RELEASE_GATE.md)。

本次没有重新构建上表的冻结安装包；原包内保留的历史未引用编译文件和旧文档已在修复记录中披露。不能将后续放行源码 SHA 当作原包构建 SHA，也不能以同版本的新包继承原附件的通过结论。自定义 Excel、HTML 模板和文献雷达继续留在 0.2。
