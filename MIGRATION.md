# 单仓库迁移说明

从本版本开始，只需克隆 `dsh-scientific-reading`。`sr_setup` 会把 npm 包内置的 Python wheel 安装到数据目录 `.venv`。

旧的 `Scientific-Reading-for-Newbies` checkout 不再参与运行，可以在新版本验收后自行归档。插件不会移动或删除旧 PDF、generation、HTML 或用户字段；旧执行命令与旧 Zotero/快速解析流程不再提供。
