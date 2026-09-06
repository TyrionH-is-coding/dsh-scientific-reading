import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'


const MANIFEST_CONTRACT = 'reader-review-manifest-v1'
const REQUIRED_CHECKS = ['desktop', 'tablet', 'mobile']
const CHECK_LABELS = {
  desktop: '桌面布局',
  tablet: '平板布局',
  mobile: '手机布局',
}

export class BrowserQaError extends Error {
  constructor(code) {
    super(code)
    this.name = 'BrowserQaError'
    this.code = code
  }
}

function uniqueSorted(values) {
  if (!Array.isArray(values) || values.some((value) => typeof value !== 'string')) {
    throw new BrowserQaError('browser_qa_input_invalid')
  }
  return [...new Set(values)].sort()
}

function sameStrings(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

async function readManifest(manifestPath) {
  let raw
  let manifest
  try {
    raw = await fs.readFile(manifestPath, 'utf8')
    manifest = JSON.parse(raw)
  } catch {
    throw new BrowserQaError('browser_qa_state_invalid')
  }
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new BrowserQaError('browser_qa_state_invalid')
  }
  return { raw, manifest }
}

export async function recordBrowserQa({ reviewRoot, revision, cases, checks }) {
  if (!Number.isSafeInteger(revision) || revision < 1) {
    throw new BrowserQaError('browser_qa_input_invalid')
  }
  const root = path.resolve(reviewRoot)
  const manifestPath = path.join(root, 'review-manifest.json')
  const { raw, manifest } = await readManifest(manifestPath)

  if (
    manifest.contract_version !== MANIFEST_CONTRACT
    || manifest.status !== 'ready'
    || manifest.candidate_stale === true
    || manifest.tests?.status !== 'passed'
    || manifest.tests?.failed !== 0
    || manifest.cases === null
    || typeof manifest.cases !== 'object'
    || Array.isArray(manifest.cases)
  ) {
    throw new BrowserQaError('browser_qa_state_invalid')
  }
  if (manifest.revision !== revision) {
    throw new BrowserQaError('browser_qa_revision_stale')
  }

  const requestedChecks = uniqueSorted(checks)
  const requiredChecks = [...REQUIRED_CHECKS].sort()
  if (!sameStrings(requestedChecks, requiredChecks)) {
    throw new BrowserQaError('browser_qa_incomplete')
  }

  const requestedCases = uniqueSorted(cases)
  const manifestCases = Object.keys(manifest.cases).sort()
  if (
    requestedCases.length === 0
    || !sameStrings(requestedCases, manifestCases)
    || requestedCases.some((caseName) => manifest.cases[caseName]?.render_status !== 'passed')
  ) {
    throw new BrowserQaError('browser_qa_case_invalid')
  }

  const browserQa = {
    status: 'passed',
    revision,
    checked_at: new Date().toISOString(),
    cases: requestedCases,
    checks: REQUIRED_CHECKS.map((id) => ({
      id,
      label: CHECK_LABELS[id],
      status: 'passed',
    })),
  }
  const updated = { ...manifest, browser_qa: browserQa }
  const temporary = path.join(
    root,
    `.review-manifest.${crypto.randomBytes(8).toString('hex')}.tmp`,
  )
  try {
    await fs.writeFile(
      temporary,
      `${JSON.stringify(updated, null, 2)}\n`,
      { encoding: 'utf8', flag: 'wx' },
    )
    if ((await fs.readFile(manifestPath, 'utf8')) !== raw) {
      throw new BrowserQaError('browser_qa_revision_stale')
    }
    await fs.rename(temporary, manifestPath)
  } finally {
    await fs.rm(temporary, { force: true })
  }
  return browserQa
}

export function parseArguments(argv) {
  const options = {
    reviewRoot: path.join(os.tmpdir(), 'dsh-scientific-reading-review'),
    revision: null,
    cases: [],
    checks: [],
  }
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === '--review-root') options.reviewRoot = argv[++index]
    else if (argument === '--revision') options.revision = Number(argv[++index])
    else if (argument === '--case') options.cases.push(argv[++index])
    else if (argument === '--desktop') options.checks.push('desktop')
    else if (argument === '--tablet') options.checks.push('tablet')
    else if (argument === '--mobile') options.checks.push('mobile')
    else throw new BrowserQaError('browser_qa_argument_invalid')
  }
  if (!options.reviewRoot || options.cases.some((value) => !value)) {
    throw new BrowserQaError('browser_qa_argument_invalid')
  }
  return options
}

async function main() {
  try {
    const result = await recordBrowserQa(parseArguments(process.argv.slice(2)))
    process.stdout.write(`${JSON.stringify({ ok: true, browser_qa: result })}\n`)
  } catch (error) {
    const code = error instanceof BrowserQaError ? error.code : 'browser_qa_failed'
    process.stderr.write(`${JSON.stringify({ ok: false, error: code })}\n`)
    process.exitCode = 1
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await main()
}
