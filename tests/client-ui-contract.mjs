import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const source = readFileSync(join(root, 'client', 'client.js'), 'utf8')

assert.match(source, /state\.countLabel\.textContent = '全部文献（' \+ state\.papers\.length \+ '）'/, '列表刷新后必须更新全部文献总数')
assert.match(source, /state\.countLabel = el\('div', 'sr-dim', '全部文献（' \+ state\.papers\.length \+ '）'\)/, '总数标签必须保存在 state 中')
assert.match(source, /min-width:420px/, '中栏必须保留可读最小宽度')
assert.match(source, /width:clamp\(340px,38%,500px\)/, '右栏必须采用桌面弹性宽度')
assert.match(source, /table-layout:fixed/, '论文表格必须使用固定列布局')
assert.match(source, /min-width:520px/, '论文表格必须保留最小宽度')
assert.match(source, /td2\.title = p\.title \|\| '\(无题名\)'/, '标题截断时必须保留完整提示')
assert.match(source, /td4\.title = p\.doi \|\| ''/, 'DOI 截断时必须保留完整提示')
assert.match(source, /white-space:nowrap/, '状态与窄列必须防止字符级换行')
assert.match(source, /text-overflow:ellipsis/, '长标题与 DOI 必须省略显示')

console.log('PASS: 文献列表计数与桌面布局契约')
