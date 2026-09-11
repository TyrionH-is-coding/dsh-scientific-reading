# 界面设计依据

本轮围绕模型连接、四套主题和右侧工作区调整。对照项目的当前官方说明，再以 DSH 实际运行界面验证。

| 参考项目 | 借鉴的交互 | 在本项目的应用 |
| --- | --- | --- |
| [Better Notes](https://github.com/windingwind/zotero-better-notes) | 阅读器右侧承载笔记，笔记保留与原条目的联系；当前版本使用笔记页签与上下文面板 | 文献库与文献设置进入宿主右侧页签；阅读问答与随记继续共享侧面板，保留当前文献与选区 |
| [Translate for Zotero](https://github.com/windingwind/zotero-pdf-translate) | 选区操作与右侧结果面板配合；只有存在目标笔记时才显示写入操作 | 按真实可用状态显示操作。模型列表只使用宿主返回的可用目录；选中文字继续由用户点击或快捷键触发问答 |
| [Ethereal Style](https://github.com/MuiseDestiny/zotero-style) | 利用状态、标签和视图减少反复切换、避免有限宽度下堆满字段 | 右侧窄栏中将分类导航整理成紧凑区，文献操作换行；不向读者显示 provider 或测试环境后缀 |
| [Actions & Tags](https://github.com/windingwind/zotero-actions-tags) | 将常用动作接到当前条目与快捷入口 | 保持现有“保存随记—打开 Excel”短路径；不额外引入自动化配置页 |
| [DeepTutor](https://github.com/HKUDS/DeepTutor) | 成套主题、预览卡片和统一主题状态 | 暖纸、纯白、深墨、雾蓝；设置、文献库和 Reader 使用同一套配色数据 |
| [Readwise Reader](https://docs.readwise.io/reader/guides/ghostreader/overview) | 右侧聊天与选区问答相互关联 | 阅读操作保留正文位置，在右侧展开结果 |

## 持续遵循

- 阅读内容占主位。辅助面板可收起，入口位置固定，收起后仍能找到。
- 普通用户只看到可操作的状态。未连接 Codex 时，不用保存的 GPT 默认偏好补造可选项，也不自动换成另一模型。
- 外观由完整预设控制。主题同时定义背景、正文、辅助文字、边框和强调色，用户不填写色值。
- 常用操作就近出现；长说明、环境标识和内部实现信息不进入主流程。
- 大量功能不等于大量入口。复用宿主页签、当前文献与现有随记数据，不复制一套工作区。

DeepTutor 的本地核对依据为 `1f2ceaf2` 的 `web/lib/theme.ts`、`ThemePreviewCard.tsx` 和外观设置页。其四套主题为 light/dark/glass/snow；本项目借鉴预设与预览结构，配色按论文阅读场景调整。
