import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const source = readFileSync(join(root, 'client', 'client.js'), 'utf8')

function loadNamedFunction(name) {
  const marker = `function ${name}(`
  const start = source.indexOf(marker)
  assert.notEqual(start, -1, `缺少可测试函数：${name}`)
  const bodyStart = source.indexOf('{', start)
  let depth = 0
  for (let i = bodyStart; i < source.length; i += 1) {
    if (source[i] === '{') depth += 1
    if (source[i] === '}') depth -= 1
    if (depth === 0) return Function(`return (${source.slice(start, i + 1)})`)()
  }
  throw new Error(`函数未闭合：${name}`)
}

const createMountController = loadNamedFunction('createMountController')
const normalizeIngestTitles = loadNamedFunction('normalizeIngestTitles')
assert.deepEqual(normalizeIngestTitles('  A paper  ', false), ['A paper'], '单篇录入必须去除首尾空白')
assert.deepEqual(normalizeIngestTitles(' A\n\n B \nA ', true), ['A', 'B'], '批量录入必须逐行去空、去重并忽略空行')
assert.deepEqual(normalizeIngestTitles('  \n ', true), [], '空白批量输入不得产生请求')
let created = 0
let disposed = 0
const roots = []
function hostFixture() {
  return {
    dataset: {},
    children: [],
    appendChild(node) { node.parentNode = this; this.children.push(node) },
    removeChild(node) { this.children.splice(this.children.indexOf(node), 1); node.parentNode = null },
  }
}
const controller = createMountController(() => {
  const rootNode = { parentNode: null, id: ++created }
  roots.push(rootNode)
  return { root: rootNode, dispose() { disposed += 1 } }
})
const host = hostFixture()
controller.ref(host)
assert.equal(created, 1, '初次挂载必须创建一次页面')
assert.equal(host.children.length, 1, '初次挂载必须只插入一个 root')
controller.ref(host)
assert.equal(created, 1, '同一稳定 ref 重渲染不得重复创建页面')
assert.equal(disposed, 0, '同一稳定 ref 重渲染不得销毁页面')
controller.ref(null)
assert.equal(disposed, 1, 'null cleanup 必须且只能销毁一次')
assert.equal(host.children.length, 0, 'null cleanup 必须移除本次挂入的 root')
assert.equal(host.dataset.srMounted, undefined, 'null cleanup 必须清除 dataset 标志')
controller.ref(null)
assert.equal(disposed, 1, '重复 null cleanup 不得重复销毁')
controller.ref(host)
assert.equal(created, 2, 'null 后同一节点必须可以重新挂载')
assert.equal(host.children.length, 1, '重新挂载后仍只能有一个 root')

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
assert.match(source, /\/sr\/api\/library[^]*method:\s*'POST'/, '添加文献必须调用本地主库 POST 接口')
assert.match(source, /aria-label', '添加文献'|aria-label', mode === 'batch' \? '批量粘贴文献' : '添加文献'/, '录入面板必须声明可访问名称')
assert.match(source, /录入成功|添加成功/, '录入完成必须显示中文成功反馈')
assert.match(source, /录入失败|添加失败/, '录入失败必须显示中文失败反馈')
assert.match(source, /ingestSubmit\.disabled =[^]*!titles\.length/, '空输入必须禁用提交')
assert.match(source, /ingestSubmitting[^]*Escape/, '提交期间不得被 Escape 中断')
assert.match(source, /ingestCancel\.disabled = ingestSubmitting/, '提交期间必须禁用取消')
assert.match(source, /ingestCancel\.type = 'button'/, '取消按钮不得误触发表单提交')
assert.match(source, /height:calc\(100vh - 76px\);min-height:0;max-height:100%/, '根布局必须限制在宿主 viewport 内并由表格区内部滚动')
assert.match(source, /\.sr-main\{min-height:0;overflow:hidden\}/, 'grid 主区必须允许收缩，避免长表格把分页挤出根容器')
assert.match(source, /\.sr-main\{padding-bottom:126px\}/, '主栏必须为宿主固定输入框预留底部安全区')
assert.match(source, /\.sr-table-wrap\{flex:1;min-height:0;overflow:auto/, '长列表必须由表格区域内部滚动')
for (const label of ['题名', '作者 / 年份', '归类', '状态', '快捷入口']) {
  assert.match(source, new RegExp(label), `缺少表头：${label}`)
}
assert.doesNotMatch(source, /下载 PDF|生成浅读/, '列表页不得出现普通阶段按钮')
for (const label of ['浅读', '开始精读', '阅读 HTML', 'PDF', '飞书', '更多', '查看历史浅读']) {
  assert.match(source, new RegExp(label), `缺少行快捷入口：${label}`)
}
assert.match(source, /role[^\n]*dialog|setAttribute\('role', 'dialog'\)/, 'drawer 必须声明 dialog role')
assert.match(source, /aria-modal/, 'drawer 必须声明 aria-modal')
assert.match(source, /Escape/, 'drawer 必须支持 Escape 关闭')
assert.match(source, /待补摘要/, '摘要缺失必须明确显示待补摘要')
assert.doesNotMatch(source, /href\s*=\s*['"]['"]/, '不得生成空 href')
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
assert.match(source, /dispose: function \(\) \{[^]*lifecycle\.dispose\(\)[^]*clearTimeout\(searchTimer\)[^]*clearTimeout\(tagTimer\)[^]*request\.abort\(\)[^]*disposed = true/, '卸载必须先失效 drawer session，再清理 timer、列表请求和动作控制器')
assert.match(source, /var mountController = createMountController\(renderLiterature\)[^]*var literatureRef = mountController\.ref[^]*ref: literatureRef/, 'slot provider 必须复用稳定 callback ref')
assert.match(source, /state\.status !== 'ready' \|\| query\.page <= 1/, '非 ready 状态必须禁用上一页')
assert.match(source, /state\.status !== 'ready' \|\| query\.page \* query\.page_size >= state\.total/, '非 ready 状态必须禁用下一页')
assert.match(source, /tagInput\.addEventListener\('input'/, '标签必须是可输入筛选控件')

console.log('PASS: 两栏文献导航 DOM、文案与查询状态契约')
