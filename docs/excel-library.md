# v0.1 文献长期管理

SQLite 为事实源。工作簿生成到文献根的 library/scientific-reading.xlsx，使用原生 Excel Table，支持整表排序与筛选，横向滚动保留文献名。

- 文献：分类、人工阅读进度、课题关系、下一步与成果入口优先；长笔记和双语摘要保留。
- 阅读成果：复用通过来源校验的 Reader 导读与已确认记录，保留证据类别、确认状态和旧证据失效状态。不显示父子会话 ID，不更改底层会话合同。
- 图表索引：按当前 PDF 清单生成，逻辑表的截图与 HTML 合并一行；只有明确指向图表证据块的记录才显示关联。不新增 AI 解图。

## 修改与同步

黄色六列对应 reading_state、project_relevance、next_action、understanding_level、personal_thoughts、user_notes。阅读进度固定为未读、在读、已读、待复读；后台生成 Reader 不自动标记为已读。

保存关闭表格后使用设置页的 Excel 刷新入口，或运行本实例引擎的 xlsx-refresh。返回 success / pending / failed、updated、rows、exported_at 与 path。文件占用或冲突时保留原表，不删除占用标记。job-status 的 detail.xlsx 汇总实际派生子作业回执；environment-status 的 library 包含最新导出。

Excel 回写逐字段比较基线、当前表和数据库。未编辑旧表不会覆盖新库值；相同修改可合并，不同修改整批暂停。空字符串是明确清空。行标识与论文 ID 一起参与校验，支持整表排序，不能只移动部分列或改隐藏身份。

对话维护使用 personal-record-update --paper-id，标准输入必须包含 fields 和同键 expected 旧值；只有六个个人字段可写，遵守已有论文范围校验。个人记录更新时间只在实际修改时更新；个人记录进入分层全文检索。library-list-v2 支持 --reading-state、--personal-recent-days、--order-by personal_updated_at。

## 迁移与恢复

v5 数据库迁移前验证备份。旧 Excel 没有基线，仅导入可以确认的三列个人内容；与现有非空值不一致时暂停核对。替换前按内容哈希归档原工作簿到 backups/xlsx，保留未映射的占位列和个人附加页。完整库备份包含数据库导出基线，不能用单独 XLSX 代替。

Windows 原生 Excel 16 已在隔离合成库完成正常打开、编辑、整表排序、保存、同步及按论文 ID 读回；工作簿公式完成原生重算。macOS Excel、Numbers、Linux LibreOffice 对新格式的原生 UI 回归仍需分别完成。
