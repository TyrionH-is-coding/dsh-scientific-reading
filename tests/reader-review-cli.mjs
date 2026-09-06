import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath, pathToFileURL } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const cliPath = path.join(repositoryRoot, 'scripts', 'reader-review.mjs')
const cliModule = await import(pathToFileURL(cliPath))

assert.deepEqual(cliModule.sourcePythonPath().split(path.delimiter), [
  path.join(repositoryRoot, 'engine', 'src'),
  path.join(repositoryRoot, 'engine'),
  repositoryRoot,
])


function runCli(args, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [cliPath, ...args], {
      cwd: repositoryRoot,
      env,
      windowsHide: true,
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const stdout = []
    const stderr = []
    child.stdout.on('data', (chunk) => stdout.push(chunk))
    child.stderr.on('data', (chunk) => stderr.push(chunk))
    child.once('error', reject)
    child.once('exit', (code) => resolve({
      code,
      stdout: Buffer.concat(stdout).toString('utf8'),
      stderr: Buffer.concat(stderr).toString('utf8'),
    }))
  })
}


function runPython(code, args) {
  const python = process.env.SCIENTIFIC_READING_PYTHON
    || process.env.PYTHON
    || (process.platform === 'win32' ? 'python.exe' : 'python3')
  return new Promise((resolve, reject) => {
    const child = spawn(python, ['-c', code, ...args], {
      cwd: repositoryRoot,
      env: {
        ...process.env,
        PYTHONPATH: [
          path.join(repositoryRoot, 'engine', 'src'),
          path.join(repositoryRoot, 'engine'),
          repositoryRoot,
        ].join(path.delimiter),
        PYTHONUTF8: '1',
        PYTHONIOENCODING: 'utf-8',
      },
      windowsHide: true,
      shell: false,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    const stdout = []
    const stderr = []
    child.stdout.on('data', (chunk) => stdout.push(chunk))
    child.stderr.on('data', (chunk) => stderr.push(chunk))
    child.once('error', reject)
    child.once('exit', (codeValue) => resolve({
      code: codeValue,
      stdout: Buffer.concat(stdout).toString('utf8'),
      stderr: Buffer.concat(stderr).toString('utf8'),
    }))
  })
}


async function waitUntil(check, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await check()) return
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  throw new Error('condition timeout')
}


async function health(port) {
  return await new Promise((resolve) => {
    const request = http.get(
      { host: '127.0.0.1', port, path: '/health', timeout: 300 },
      (response) => {
        const chunks = []
        response.on('data', (chunk) => chunks.push(chunk))
        response.on('end', () => {
          try {
            resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')))
          } catch {
            resolve(null)
          }
        })
      },
    )
    request.on('timeout', () => request.destroy())
    request.on('error', () => resolve(null))
  })
}


const sanitized = cliModule.sanitizedEnvironment({
  PATH: process.env.PATH,
  MINERU_API_TOKEN: 'secret-mineru',
  MINERU_API_KEY: 'secret-key',
  FEISHU_APP_ID: 'secret-id',
  FEISHU_APP_SECRET: 'secret-feishu',
  SR_SCANSCI_PROVIDER_WRAPPER: 'secret-wrapper',
  SR_SCANSCI_PROVIDER_PYTHON: 'secret-python',
})
for (const name of [
  'MINERU_API_TOKEN',
  'MINERU_API_KEY',
  'FEISHU_APP_ID',
  'FEISHU_APP_SECRET',
  'SR_SCANSCI_PROVIDER_WRAPPER',
  'SR_SCANSCI_PROVIDER_PYTHON',
]) assert.equal(sanitized[name], '', `${name} 必须从快速审核子进程清空`)
assert.equal(sanitized.SR_SCANSCI_DISABLE_INSTITUTION, '1')

const options = cliModule.hiddenSpawnOptions({ cwd: repositoryRoot })
assert.equal(options.windowsHide, true)
assert.equal(options.shell, false)
assert.equal(options.cwd, repositoryRoot)

const defaultReviewRoot = path.join(os.tmpdir(), 'dsh-scientific-reading-review')
const pausedDefaultServer = await cliModule.stopServer(defaultReviewRoot)
const base = await fs.mkdtemp(path.join(os.tmpdir(), 'reader-review-cli-test-'))
const reviewRoot = path.join(base, 'review')
let ownedPid = null
try {
  const first = await runCli([
    '--case', 'formula-outline',
    '--new-session',
    '--review-root', reviewRoot,
  ], {
    ...process.env,
    MINERU_API_TOKEN: 'must-not-be-used',
    FEISHU_APP_SECRET: 'must-not-be-used',
  })
  assert.equal(first.code, 0, first.stderr)
  const firstLines = first.stdout.trim().split(/\r?\n/).filter(Boolean)
  assert.equal(firstLines.length, 1)
  const firstSummary = JSON.parse(firstLines[0])
  assert.deepEqual(
    {
      ok: firstSummary.ok,
      url: firstSummary.url,
      case: firstSummary.case,
      server: firstSummary.server,
    },
    {
      ok: true,
      url: 'http://127.0.0.1:8895/review',
      case: 'formula-outline',
      server: 'started',
    },
  )
  const serverMetadata = JSON.parse(
    await fs.readFile(path.join(reviewRoot, 'server.json'), 'utf8'),
  )
  ownedPid = serverMetadata.pid
  assert.equal((await health(8895)).pid, ownedPid)
  const baselinePath = path.join(
    reviewRoot,
    'baseline',
    'formula-outline',
    'reader.html',
  )
  const baseline = await fs.readFile(baselinePath)

  const second = await runCli(['--review-root', reviewRoot])
  assert.equal(second.code, 0, second.stderr)
  const secondSummary = JSON.parse(second.stdout.trim())
  assert.equal(secondSummary.server, 'reused')
  assert.equal(secondSummary.revision, firstSummary.revision + 1)
  assert.equal((await health(8895)).pid, ownedPid)
  assert.deepEqual(await fs.readFile(baselinePath), baseline)

  await fs.writeFile(
    path.join(reviewRoot, 'server.json'),
    JSON.stringify({ ...serverMetadata, token: 'identity-mismatch' }),
    'utf8',
  )
  const mismatch = await runCli(['--review-root', reviewRoot])
  assert.notEqual(mismatch.code, 0)
  assert.equal(
    JSON.parse(mismatch.stderr.trim().split(/\r?\n/).at(-1)).error_code,
    'review_server_identity_mismatch',
  )
  assert.equal((await health(8895)).pid, ownedPid)
  await fs.writeFile(
    path.join(reviewRoot, 'server.json'),
    JSON.stringify(serverMetadata),
    'utf8',
  )

  const stopped = await runCli(['--review-root', reviewRoot, '--stop'])
  assert.equal(stopped.code, 0, stopped.stderr)
  assert.equal(JSON.parse(stopped.stdout.trim()).server, 'stopped')
  await waitUntil(async () => await health(8895) === null)
  await assert.rejects(fs.stat(path.join(reviewRoot, 'server.json')), /ENOENT/)
  ownedPid = null

  const missingRoot = path.join(base, 'missing-session')
  const missing = await runCli(['--review-root', missingRoot])
  assert.notEqual(missing.code, 0)
  const error = JSON.parse(missing.stderr.trim().split(/\r?\n/).at(-1))
  assert.equal(error.error_code, 'review_source_required')
  assert.deepEqual(error.available_cases, [
    'formula-outline',
    'superscript-text',
    'figures-captions',
  ])

  const dataRoot = path.join(base, 'data')
  const paperSetup = await runPython(`
import hashlib
import json
import sys
from pathlib import Path
from scientific_reading.models import JobState, PaperMetadata, StageRecord
from scientific_reading.workspace import PaperWorkspace
from scripts.reader_review_fixtures import (
    FIXTURE_METHOD,
    FIXTURE_PARSER_VERSION,
    fixture_path,
    materialize_fixture,
)

data_root = Path(sys.argv[1])
paper_id = "fixture_real_paper"
payload = json.loads(fixture_path("formula-outline").read_text(encoding="utf-8"))
metadata = PaperMetadata.from_dict(payload["metadata"])
base = PaperWorkspace.create_for_paper_id(data_root, paper_id, metadata)
source_bytes = b"%PDF-1.4\\n% deterministic reader review fixture\\n% formula-outline\\n"
source_sha = hashlib.sha256(source_bytes).hexdigest()
materialize_fixture(
    "formula-outline",
    base.root / "generations" / source_sha[:16],
)
base.save_job(JobState(
    paper_id=paper_id,
    status="full_read_ready",
    stages={
        "paper_parse_upgrade": StageRecord(
            status="completed",
            result={
                "active_parsed_dir": "parsed/mineru",
                "active_workspace": f"generations/{source_sha[:16]}",
                "source_sha256": source_sha,
                "method": FIXTURE_METHOD,
                "mineru_version": FIXTURE_PARSER_VERSION,
            },
        )
    },
))
`, [dataRoot])
  assert.equal(paperSetup.code, 0, paperSetup.stderr)
  const paperReviewRoot = path.join(base, 'paper-review')
  const paperRun = await runCli([
    '--paper-id', 'fixture_real_paper',
    '--data-root', dataRoot,
    '--new-session',
    '--review-root', paperReviewRoot,
  ])
  assert.equal(paperRun.code, 0, paperRun.stderr)
  const paperSummary = JSON.parse(paperRun.stdout.trim())
  assert.equal(paperSummary.case, 'fixture_real_paper')
  const paperServer = JSON.parse(
    await fs.readFile(path.join(paperReviewRoot, 'server.json'), 'utf8'),
  )
  ownedPid = paperServer.pid
  const paperStop = await runCli(['--review-root', paperReviewRoot, '--stop'])
  assert.equal(paperStop.code, 0, paperStop.stderr)
  ownedPid = null

  const sentinel = http.createServer((_request, response) => {
    response.end('unknown-service')
  })
  await new Promise((resolve) => sentinel.listen(8895, '127.0.0.1', resolve))
  try {
    const occupiedRoot = path.join(base, 'occupied-review')
    const occupied = await runCli([
      '--case', 'formula-outline',
      '--new-session',
      '--review-root', occupiedRoot,
    ])
    assert.notEqual(occupied.code, 0)
    assert.equal(
      JSON.parse(occupied.stderr.trim().split(/\r?\n/).at(-1)).error_code,
      'review_port_in_use',
    )
    assert.equal(sentinel.listening, true)
  } finally {
    const closed = new Promise((resolve) => sentinel.close(resolve))
    sentinel.closeAllConnections?.()
    await closed
  }

  console.log('PASS: Reader 一键审核命令、服务复用和停止合同通过')
} finally {
  if (ownedPid !== null) {
    await runCli(['--review-root', reviewRoot, '--stop']).catch(() => {})
  }
  await fs.rm(base, { recursive: true, force: true })
  if (pausedDefaultServer === 'stopped') {
    await cliModule.startOrReuseServer(defaultReviewRoot)
  }
}
