// scripts/verify-live.mjs — 上线验证（注入器恢复后执行）：路由 / 文献页 client / 库状态
// 用法：node scripts/verify-live.mjs [baseUrl]
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dirname } from 'node:path'

const base = process.argv[2] || 'http://127.0.0.1:3080'
const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const failures = []

async function get(path) {
  const res = await fetch(base + path)
  const text = await res.text()
  return { status: res.status, text }
}

// 1) 宿主路由
const papers = await get('/sr/api/papers')
if (papers.status === 200) {
  try {
    const data = JSON.parse(papers.text)
    console.log('OK  /sr/api/papers  条目数: ' + (data.papers || []).length)
  } catch { failures.push('/sr/api/papers 非 JSON') }
} else {
  failures.push('/sr/api/papers 状态 ' + papers.status + '（未生效，需重载/重注入）')
}

const detail = await get('/sr/api/paper/doi_10.48550_arxiv.1706.03762')
if (detail.status !== 200) failures.push('/sr/api/paper/<id> 状态 ' + detail.status)
else console.log('OK  /sr/api/paper/<id>  详情可用')

// 2) 文献页 client 包（client-modules 服务路径）
const clientUrl = '/plugins/@dsh-external/dsh-scientific-reading/client.js'
const client = await get(clientUrl)
if (client.status === 200 && client.text.includes('__ModuleLoader__')) {
  console.log('OK  文献页 client 包已服务')
  // 2b) 注册契约校验（防"bundle 服务但浏览器从未注册"盲区）：
  //     __ModuleLoader__.load 的 id 必须是包名（不能带 /client 后缀）
  const loadIdMatch = client.text.match(/__ModuleLoader__\.load\(\{\s*id:\s*['"]([^'"]+)['"]/)
  if (!loadIdMatch || loadIdMatch[1] !== '@dsh-external/dsh-scientific-reading') {
    failures.push('client bundle 注册 id 错误（' + (loadIdMatch ? loadIdMatch[1] : '缺失') + '，应为 @dsh-external/dsh-scientific-reading）——浏览器端将报 loaded without registering')
  } else {
    console.log('OK  client 注册 id = 包名（浏览器端可注册）')
  }
  //     组件必须是 React 元素 + ref 桥接（返回裸 DOM 节点会导致 React 崩 → data-slot-error）
  if (!client.text.includes("React.createElement('div', { ref:") && !client.text.includes('React.createElement("div", { ref:')) {
    failures.push('client 组件未用 React.createElement ref 桥接（返回裸 DOM 会被 React 拒绝）')
  } else {
    console.log('OK  client 组件为 React 桥接形式（可真实渲染）')
  }
} else {
  failures.push('文献页 client 包未服务（' + client.status + '）——需宿主重启/重注入使 dsh.client 生效')
}

// 3) 库状态同步（worker 钩子生效后 parsed/quick_read 状态应出现）
try {
  const data = JSON.parse(papers.text)
  const paper = (data.papers || []).find((p) => p.paper_id === 'doi_10.48550_arxiv.1706.03762')
  if (paper) console.log('OK  库状态: ' + (paper.status || '?') + (paper.job_status ? '（job: ' + paper.job_status + '）' : ''))
  else failures.push('库中找不到测试论文（预期至少一篇）')
} catch { /* 上面已报 */ }

if (failures.length) {
  console.error('VERIFY FAIL:')
  failures.forEach((f) => console.error('  - ' + f))
  console.error('提示：若 dev_* 工具可用，先 dev_reload_package（或重启宿主后 dev_inject_plugin）再验证。')
  process.exit(1)
}
console.log('PASS: 文献工作流上线验证通过')
