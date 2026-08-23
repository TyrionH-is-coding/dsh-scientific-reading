import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

const routes = await readFile(new URL('../src/routes.ts', import.meta.url), 'utf8')
const tools = await readFile(new URL('../src/library_tools.ts', import.meta.url), 'utf8')
const cli = await readFile(new URL('../src/cli.ts', import.meta.url), 'utf8')

assert.equal((routes.match(/engineDerivedEnqueue\(config/g) ?? []).length, 1)
assert.equal((tools.match(/engineDerivedEnqueue\(config/g) ?? []).length, 1)
assert.equal(routes.includes('engineStartDetached'), false)
assert.equal(routes.includes('engineFeishuProbe'), false)
assert.equal(tools.includes('engineStartDetached'), false)
assert.equal(routes.includes("writeFile(join(root, 'metadata.json')"), false)
assert.equal(tools.includes("writeFile(metaPath, JSON.stringify(metadata"), false)
assert.match(tools, /name: 'sr_abstract_submit'/)
assert.match(cli, /\['abstract-read-submit', '--job-id', jobId, '--input', '-'\]/)
assert.match(cli, /\['derived-enqueue', '--paper-id', paperId\]/)

console.log('PASS: Phase 1 插件只提交一次持久 derived-enqueue，Abstract 使用 agent submit，旧 detached 未接入入口')
