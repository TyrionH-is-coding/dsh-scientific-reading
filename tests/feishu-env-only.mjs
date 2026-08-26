// 回归测试：离线插件测试显式清理飞书环境，不从设置或测试夹具注入凭证。
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { engineFeishuProbe } from '../lib/cli.js'
import { Config } from '../lib/config.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/)
  .map((line) => line.trim())
  .find((line) => line.toLowerCase().endsWith('.exe'))

assert.ok(python, '测试需要 PATH 中存在 python.exe')

const root = await mkdtemp(join(tmpdir(), 'sr-feishu-env-'))
const packageDir = join(root, 'scientific_reading')
await mkdir(packageDir)
await writeFile(join(packageDir, '__init__.py'), '', 'utf8')
await writeFile(
  join(packageDir, '__main__.py'),
  [
    'import json',
    'import os',
    'print(json.dumps({',
    '    "app_id": os.environ.get("FEISHU_APP_ID"),',
    '    "app_secret": os.environ.get("FEISHU_APP_SECRET"),',
    '}))',
  ].join('\n'),
  'utf8',
)

const previous = { pythonPath: process.env.PYTHONPATH }

try {
  delete process.env.FEISHU_APP_ID
  delete process.env.FEISHU_APP_SECRET
  process.env.PYTHONPATH = previous.pythonPath
    ? root + delimiter + previous.pythonPath
    : root

  const config = {
    dataRoot: root,
    python: 'python',
    scansciExe: 'scansci-pdf',
    school: '',
    legalOnly: true,
    outputDir: '',
    loginType: 'carsi',
    scansciPython: '',
    enginePython: python,
    feishuConfig: join(root, 'feishu-config.json'),
    // 模拟升级前遗留或外部调用方伪造的设置字段。
    feishuAppId: 'settings-app-id',
    feishuAppSecret: 'settings-secret',
  }

  const result = await engineFeishuProbe(config)
  assert.equal(result.ok, true)
  assert.equal(result.json?.app_id, null)
  assert.equal(result.json?.app_secret, null)

  const schema = JSON.stringify(Config.toJSON())
  assert.equal(schema.includes('feishuAppId'), false, 'schema 不得暴露飞书 App ID 设置')
  assert.equal(schema.includes('feishuAppSecret'), false, 'schema 不得暴露飞书 App Secret 设置')

  const client = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  assert.equal(client.includes('feishuAppId'), false, '设置卡片不得出现飞书 App ID')
  assert.equal(client.includes('feishuAppSecret'), false, '设置卡片不得出现飞书 App Secret')
} finally {
  delete process.env.FEISHU_APP_ID
  delete process.env.FEISHU_APP_SECRET
  if (previous.pythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previous.pythonPath
  await rm(root, { recursive: true, force: true })
}

console.log('PASS: 离线测试不注入飞书凭证，且不暴露为插件设置')
