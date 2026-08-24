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
assert.match(source, /page_size: 50/, '服务器分页默认必须为 50')
assert.match(source, /Math\.min\(100,/, 'page_size 必须限制为最大 100')
assert.match(source, /var queryStore = createQueryStore/, '必须由一个明确 store 管理 query 状态')
assert.match(source, /setTimeout\([^]*250\)/, '搜索必须使用 250ms debounce')
assert.match(source, /new AbortController\(\)/, '新请求必须可取消旧请求')
assert.match(source, /正在加载文献|没有符合条件的文献|加载失败/, '必须提供中文加载、空与错误状态')

console.log('PASS: 两栏文献导航 DOM、文案与查询状态契约')
