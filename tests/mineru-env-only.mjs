// 回归测试：MinerU API 凭证只从宿主环境继承，不进入插件设置或命令参数。
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { delimiter, join } from 'node:path'
import { tmpdir } from 'node:os'

import { engineStartFullRead } from '../lib/cli.js'
import { Config } from '../lib/config.js'

const python = execFileSync('where.exe', ['python'], { encoding: 'utf8' })
  .split(/\r?\n/)
  .map((line) => line.trim())
  .find((line) => line.toLowerCase().endsWith('.exe'))
assert.ok(python, '测试需要 PATH 中存在 python.exe')

const root = await mkdtemp(join(tmpdir(), 'sr-mineru-env-'))
const packageDir = join(root, 'scientific_reading')
await mkdir(packageDir)
await writeFile(join(packageDir, '__init__.py'), '', 'utf8')
await writeFile(
  join(packageDir, '__main__.py'),
  [
    'import json, os, sys',
    'print(json.dumps({',
    '  "token": os.environ.get("MINERU_API_TOKEN"),',
    '  "argv": sys.argv[1:],',
    '}))',
  ].join('\n'),
  'utf8',
)

const previous = {
  pythonPath: process.env.PYTHONPATH,
  token: process.env.MINERU_API_TOKEN,
}

try {
  delete process.env.MINERU_API_TOKEN
  process.env.PYTHONPATH = previous.pythonPath ? root + delimiter + previous.pythonPath : root
  process.env.MINERU_API_TOKEN = 'fictional-mineru-token'
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
    feishuConfig: '',
    mineruApiToken: 'settings-token-must-be-ignored',
  }

  const result = await engineStartFullRead(config, 'paper-1')
  assert.equal(result.ok, true)
  assert.equal(result.json?.token, 'fictional-mineru-token')
  assert.equal(JSON.stringify(result.json?.argv).includes('fictional-mineru-token'), false)

  const schema = JSON.stringify(Config.toJSON())
  assert.equal(schema.includes('mineruApiToken'), false, 'schema 不得暴露 MinerU token 设置')
  const client = await readFile(new URL('../lib/client.js', import.meta.url), 'utf8')
  assert.equal(client.includes('mineruApiToken'), false, '设置卡片不得出现 token 输入框')
} finally {
  delete process.env.MINERU_API_TOKEN
  if (previous.token !== undefined) process.env.MINERU_API_TOKEN = previous.token
  if (previous.pythonPath === undefined) delete process.env.PYTHONPATH
  else process.env.PYTHONPATH = previous.pythonPath
  await rm(root, { recursive: true, force: true })
}

console.log('PASS: MinerU API token 仅由宿主环境继承且不进入参数或设置')
