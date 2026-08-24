import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const source = readFileSync(join(root, 'client', 'client.js'), 'utf8')

assert.match(source, /'sr-sidebar'/, '根布局必须包含 sidebar')
assert.match(source, /'sr-main'/, '根布局必须包含 main list')
assert.match(source, /'sr-drawer'/, '详情必须是 overlay drawer 占位')
assert.doesNotMatch(source, /'sr-right'/, '不得保留常驻第三栏')
for (const legacy of ['sr-legacy-detail', '/sr/api/papers', 'function refreshList', 'function selectPaper', 'function renderTable', 'function renderDetail']) {
  assert.doesNotMatch(source, new RegExp(legacy), `必须删除旧三栏死代码：${legacy}`)
}
assert.match(source, /全部文献/, '左侧必须有全部文献')
assert.match(source, /待归类/, '左侧必须有待归类')
assert.doesNotMatch(source, /收件箱|待整理/, '不得出现未批准的收件箱或待整理')
assert.match(source, /aria-expanded/, 'sidebar 开关必须暴露 aria-expanded')
assert.match(source, /--sr-sidebar-width:240px/, 'sidebar 展开宽度必须为 240px')
assert.match(source, /--sr-sidebar-width-collapsed:56px/, 'sidebar 收起后必须只保留图标和开关')
for (const label of ['搜索题名、作者或 DOI', '添加文献', '批量粘贴', '状态', '标签', '最近入库']) {
  assert.match(source, new RegExp(label), `缺少顶部控件：${label}`)
}
for (const label of ['题名', '作者 / 年份', '归类', '状态', '快捷入口']) {
  assert.match(source, new RegExp(label), `缺少表头：${label}`)
}
assert.doesNotMatch(source, /下载 PDF|生成浅读/, '列表页不得出现普通阶段按钮')
assert.doesNotMatch(source, /function quickLink|function openDrawer|sr-paper-row[^\n]*addEventListener/, 'Task 2 不得提前实现行详情和快捷操作')
assert.match(source, /el\('td', 'sr-entries', '—'\)/, '快捷入口列必须仅保留不可交互占位')
assert.match(source, /__unclassified__/, '待归类必须使用正式哨兵')
assert.doesNotMatch(source, /__unfiled__/, '不得使用旧的待归类哨兵')
assert.match(source, /Array\.isArray\(folders\)/, 'folders API 顶层数组必须被识别')
assert.match(source, /folder\.folder_id/, '文件夹查询必须使用 folder_id')
assert.match(source, /updateNavigationSelection/, 'aria-current 必须随当前文件夹更新')
assert.match(source, /page_size: 50/, '服务器分页默认必须为 50')
assert.match(source, /Math\.min\(100,/, 'page_size 必须限制为最大 100')
assert.match(source, /var queryStore = createQueryStore/, '必须由一个明确 store 管理 query 状态')
assert.match(source, /setTimeout\([^]*250\)/, '搜索必须使用 250ms debounce')
assert.match(source, /new AbortController\(\)/, '新请求必须可取消旧请求')
assert.match(source, /正在加载文献|没有符合条件的文献|加载失败/, '必须提供中文加载、空与错误状态')
assert.match(source, /重试/, '错误态必须提供中文重试操作')
assert.match(source, /var disposed = false/, '每次 mount 必须有私有 disposed 状态')
assert.match(source, /var requestSequence = 0/, '每次 mount 必须有私有请求序列')
assert.match(source, /sequence !== requestSequence/, '过时响应不得覆盖新请求')
assert.match(source, /clearTimeout\(searchTimer\)[^]*clearTimeout\(tagTimer\)[^]*request\.abort\(\)[^]*disposed = true/, '卸载必须清理两个 timer、请求并标记 disposed')
assert.match(source, /else if \(mount\) \{ mount\.dispose\(\); mount = null; \}/, 'React ref 的 null 分支必须明确 cleanup')
assert.match(source, /state\.status !== 'ready' \|\| query\.page <= 1/, '非 ready 状态必须禁用上一页')
assert.match(source, /state\.status !== 'ready' \|\| query\.page \* query\.page_size >= state\.total/, '非 ready 状态必须禁用下一页')
assert.match(source, /tagInput\.addEventListener\('input'/, '标签必须是可输入筛选控件')

console.log('PASS: 两栏文献导航 DOM、文案与查询状态契约')
