import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const expectedTools = [
  'sr_setup', 'sr_scansci_status', 'sr_scansci_fetch', 'sr_scansci_login', 'sr_scansci_set_school',
  'sr_start_full_read', 'sr_continue_full_read', 'sr_attach_pdf', 'sr_export_assets', 'sr_ingest',
  'sr_abstract_submit', 'sr_library_list', 'sr_folder_manage', 'sr_classification_apply',
  'sr_classification_undo', 'sr_feishu_resync', 'sr_job_status',
]

const toolSource = [
  readFileSync(join(root, 'src', 'tools.ts'), 'utf8'),
  readFileSync(join(root, 'src', 'library_tools.ts'), 'utf8'),
].join('\n')
const actualTools = [...toolSource.matchAll(/name:\s*'(sr_[^']+)'/g)].map((match) => match[1])
assert.deepEqual(actualTools.sort(), expectedTools.sort(), '运行工具必须严格等于当前白名单')

function filesUnder(path) {
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    const child = join(path, entry.name)
    if (entry.isDirectory()) return entry.name === '__pycache__' ? [] : filesUnder(child)
    return /\.(?:ts|js|py)$/.test(entry.name) ? [child] : []
  })
}

const productionFiles = [
  ...filesUnder(join(root, 'src')),
  ...filesUnder(join(root, 'client')),
  ...filesUnder(join(root, 'engine', 'src')),
  join(root, 'engine', 'reader', 'build_reader.py'),
  join(root, 'README.md'),
  join(root, 'package.json'),
]
const forbidden = /Scientific-Reading-for-Newbies|PyMuPDF|\bfitz\b|local[-_ ]cli|mineru_runner|quick[_ -]?read|sr_parse|sr_full_read|sr_feishu_preview|sr_feishu_sync|sr_zotero_/i
for (const file of productionFiles) {
  const source = readFileSync(file, 'utf8')
  assert.doesNotMatch(source, forbidden, `发现淘汰运行路线：${relative(root, file)}`)
}

console.log('PASS: 生产运行面严格等于当前单仓库白名单')
