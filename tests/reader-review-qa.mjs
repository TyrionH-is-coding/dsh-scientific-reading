import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const scriptPath = path.join(repositoryRoot, 'scripts', 'reader-review-qa.mjs')
const reviewQa = await import(pathToFileURL(scriptPath))

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'reader-review-qa-test-'))
const manifestPath = path.join(root, 'review-manifest.json')
const original = {
  contract_version: 'reader-review-manifest-v1',
  revision: 14,
  status: 'ready',
  selected_case: 'formula-outline',
  repository_commit: '0123456789abcdef',
  cases: {
    'formula-outline': { render_status: 'passed' },
    'superscript-text': { render_status: 'passed' },
    'figures-captions': { render_status: 'passed' },
  },
  tests: { status: 'passed', passed: 9, failed: 0 },
  browser_qa: { status: 'pending', checks: [] },
}

async function resetManifest() {
  await fs.writeFile(manifestPath, `${JSON.stringify(original, null, 2)}\n`, 'utf8')
}

try {
  await resetManifest()
  const result = await reviewQa.recordBrowserQa({
    reviewRoot: root,
    revision: 14,
    cases: ['formula-outline', 'superscript-text', 'figures-captions'],
    checks: ['desktop', 'tablet', 'mobile'],
  })
  assert.equal(result.status, 'passed')
  assert.deepEqual(result.cases, [
    'figures-captions',
    'formula-outline',
    'superscript-text',
  ])
  assert.deepEqual(result.checks.map((item) => item.status), [
    'passed',
    'passed',
    'passed',
  ])

  const saved = JSON.parse(await fs.readFile(manifestPath, 'utf8'))
  assert.deepEqual(
    { ...saved, browser_qa: original.browser_qa },
    original,
    '受控入口只能更新 browser_qa',
  )
  assert.deepEqual(saved.browser_qa, result)
  assert.deepEqual(
    (await fs.readdir(root)).sort(),
    ['review-manifest.json'],
    '原子写入不得残留临时文件',
  )

  for (const input of [
    {
      revision: 13,
      cases: ['formula-outline', 'superscript-text', 'figures-captions'],
      checks: ['desktop', 'tablet', 'mobile'],
      error: 'browser_qa_revision_stale',
    },
    {
      revision: 14,
      cases: ['formula-outline', 'superscript-text', 'figures-captions'],
      checks: ['desktop', 'tablet'],
      error: 'browser_qa_incomplete',
    },
    {
      revision: 14,
      cases: ['formula-outline', 'unknown'],
      checks: ['desktop', 'tablet', 'mobile'],
      error: 'browser_qa_case_invalid',
    },
  ]) {
    await resetManifest()
    await assert.rejects(
      reviewQa.recordBrowserQa({ reviewRoot: root, ...input }),
      new RegExp(input.error),
    )
    assert.deepEqual(
      JSON.parse(await fs.readFile(manifestPath, 'utf8')),
      original,
      '拒绝输入时不得改写 manifest',
    )
  }

  await resetManifest()
  const notReady = { ...original, status: 'failed' }
  await fs.writeFile(manifestPath, `${JSON.stringify(notReady, null, 2)}\n`, 'utf8')
  await assert.rejects(
    reviewQa.recordBrowserQa({
      reviewRoot: root,
      revision: 14,
      cases: ['formula-outline', 'superscript-text', 'figures-captions'],
      checks: ['desktop', 'tablet', 'mobile'],
    }),
    /browser_qa_state_invalid/,
  )
} finally {
  await fs.rm(root, { recursive: true, force: true })
}

console.log('PASS: Reader 浏览器 QA 仅在当前 revision 完整通过后原子写回')
