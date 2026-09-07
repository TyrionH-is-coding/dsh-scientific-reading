import { execFile, spawn } from 'node:child_process'
import { engineScopeEnvironment } from './engine_scope.js'
import { access, mkdir, readFile, writeFile, rename, readdir } from 'node:fs/promises'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { fileURLToPath } from 'node:url'
import type { Config } from './config.js'
import { resolveOutputDir, resolveDataRoot, scansciDataDir } from './config.js'

// 垫片脚本路径（相对本包，junction 后同样可达）
const WRAP_REL = '../scripts/scansci_wrap.py'

/**
 * scansci-pdf CLI 适配器（Phase 0）。
 * 只做确定性包装：子进程调用 + JSON 解析 + 配置读写；不做任何判断。
 */

export interface RunResult {
  exitCode: number
  stdout: string
  stderr: string
}

const MAX_BUFFER = 64 * 1024 * 1024

export function runCommand(
  exe: string,
  args: string[],
  opts: { timeoutMs?: number; env?: NodeJS.ProcessEnv; input?: string } = {},
): Promise<RunResult> {
  return new Promise((resolve) => {
    const child = execFile(
      exe,
      args,
      {
        encoding: 'utf8',
        maxBuffer: MAX_BUFFER,
        windowsHide: true,
        timeout: opts.timeoutMs ?? 60_000,
        env: {
          ...process.env,
          TERM: 'dumb',
          NO_COLOR: '1',
          PYTHONIOENCODING: 'utf-8',
          ...(opts.env ?? {}),
        },
      },
      (error, stdout, stderr) => {
        const exitCode = error && typeof (error as { code?: unknown }).code === 'number'
          ? (error as { code: number }).code
          : error ? 1 : 0
        resolve({ exitCode, stdout: stdout ?? '', stderr: stderr ?? '' })
      },
    )
    if (opts.input !== undefined) child.stdin?.end(opts.input)
    else child.stdin?.end()
    // 超时由 execFile 的 timeout 处理（SIGTERM）；这里兜底清理
    child.on('error', () => { /* 已由回调处理 */ })
  })
}

/**
 * 从混合输出里提取第一个可解析的 JSON 对象。
 * scansci 的 to_json 是 indent=2 的多行结构，rich 控制台还会混入其他行，
 * 所以按“{ 开头的行 → 花括号配平”提取。
 */
export function extractJson(stdout: string): Record<string, unknown> | null {
  return extractJsonValue(stdout) as Record<string, unknown> | null
}

/** 通用 JSON 提取：对象或数组（library-list/search 输出 JSON 数组） */
export function extractJsonValue(stdout: string): unknown {
  const lines = stdout.split(/\r?\n/)
  for (let i = 0; i < lines.length; i++) {
    const first = lines[i].trim().charAt(0)
    if (first !== '{' && first !== '[') continue
    let buf = ''
    let depth = 0
    let inString = false
    let escaped = false
    for (let j = i; j < lines.length; j++) {
      buf += (buf ? '\n' : '') + lines[j]
      for (const ch of lines[j]) {
        if (inString) {
          if (escaped) { escaped = false; continue }
          if (ch === '\\') { escaped = true; continue }
          if (ch === '"') inString = false
          continue
        }
        if (ch === '"') { inString = true; continue }
        if (ch === '{' || ch === '[') depth++
        else if (ch === '}' || ch === ']') depth--
      }
      if (depth === 0) {
        try {
          const parsed = JSON.parse(buf)
          if (parsed !== null && typeof parsed === 'object') return parsed
        } catch { /* 下一个候选起点 */ }
        break
      }
    }
  }
  return null
}

// ── scansci-pdf 运行入口（fetch 走垫片；其余命令走 exe）────────────

export function wrapScriptPath(): string {
  return fileURLToPath(new URL(WRAP_REL, import.meta.url))
}

/** OA 使用显式解释器或插件托管环境，不自动复用用户级 ScanSci 工具。 */
export async function resolveScansciPython(config: Config): Promise<string | null> {
  if (config.scansciPython.trim()) {
    try { await access(config.scansciPython.trim()); return config.scansciPython.trim() } catch { /* fallthrough */ }
  }
  const candidates = [config.enginePython?.trim(), engineVenvPython(resolveDataRoot(config))].filter((value): value is string => Boolean(value))
  for (const c of candidates) {
    try { await access(c); return c } catch { /* 继续 */ }
  }
  return null
}

/** A 的下载只能走固定 OA wrapper，缺失时不回退综合下载器。 */
export async function runScansci(
  exe: string,
  args: string[],
  config: Config,
  opts: { timeoutMs?: number; useWrap?: boolean; env?: NodeJS.ProcessEnv; input?: string } = {},
): Promise<RunResult> {
  if (args[0] !== 'fetch') return { exitCode: 1, stdout: '', stderr: 'oa_only_operation_not_supported' }
  const python = await resolveScansciPython(config)
  const wrap = wrapScriptPath()
  if (!python) return { exitCode: 1, stdout: '', stderr: 'oa_provider_unavailable' }
  try { await access(wrap) } catch { return { exitCode: 1, stdout: '', stderr: 'oa_provider_unavailable' } }
  return runCommand(python, [wrap, ...args], { ...opts, env: { ...opts.env, SR_SCANSCI_DISABLE_INSTITUTION: '1' } })
}

// ── scansci-pdf 探活 ──────────────────────────────────────────────

export async function probeScansci(exe: string): Promise<boolean> {
  const r = await runCommand(exe, ['--help'], { timeoutMs: 15_000 })
  return r.exitCode === 0
}

export async function probeOaProvider(config: Config): Promise<boolean> {
  const python = await resolveScansciPython(config)
  if (!python) return false
  const result = await runCommand(python, [wrapScriptPath(), 'check'], { timeoutMs: 15_000 })
  const status = extractJson(result.stdout)
  return result.exitCode === 0 && status?.status === 'ready' && status?.version === '1.9.0'
}

export async function doctorScansci(exe: string): Promise<string> {
  const r = await runCommand(exe, ['doctor'], { timeoutMs: 30_000 })
  return r.exitCode === 0 ? r.stdout : (r.stderr || r.stdout).slice(-3000)
}

// ── 安装 ──────────────────────────────────────────────────────────

export async function installScansci(python: string): Promise<RunResult> {
  const requirements = fileURLToPath(new URL('../scripts/oa-requirements.txt', import.meta.url))
  return runCommand(python, ['-m', 'pip', 'install', '--disable-pip-version-check', '--require-hashes', '--no-deps', '--no-index', '-r', requirements], {
    timeoutMs: 10 * 60_000,
  })
}

// ── 合法来源配置（默认关灰色来源）──────────────────────────────────

export interface LegalConfigState {
  path: string
  legalOnly: boolean
  school: string
  outputDir: string
  existed: boolean
  changed: boolean
}

export async function readScansciConfig(config: Config): Promise<Record<string, unknown>> {
  const file = join(scansciDataDir(config), 'config.json')
  try {
    return JSON.parse(await readFile(file, 'utf8')) as Record<string, unknown>
  } catch {
    return {}
  }
}

export async function ensureScansciConfig(config: Config): Promise<LegalConfigState> {
  const dir = scansciDataDir(config)
  const file = join(dir, 'config.json')
  let existed = true
  let current: Record<string, unknown>
  try {
    current = JSON.parse(await readFile(file, 'utf8'))
  } catch {
    existed = false
    current = {}
  }
  const target: Record<string, unknown> = {
    download_strategy: 'oa_only',
    scihub_enabled: false,
    auto_relogin: false,
  }
  const changed = !existed || JSON.stringify(current) !== JSON.stringify(target)
  if (changed) {
    await mkdir(dir, { recursive: true })
    const tmp = file + '.tmp'
    await writeFile(tmp, JSON.stringify(target, null, 2) + '\n', 'utf8')
    await rename(tmp, file)
  }
  return {
    path: file,
    legalOnly: true,
    school: '',
    outputDir: resolveOutputDir(config),
    existed,
    changed,
  }
}

// ── 下载 ──────────────────────────────────────────────────────────

export interface PaperInfo {
  doi: string
  title: string
  authors: string[]
  journal: string
  year: number | null
  source: string
  url: string
  pdf_path: string
}

export interface FetchOutcome {
  status: string
  quality: string
  reason?: string
  next_action?: { kind: string; message: string; command?: string } | null
  paper?: PaperInfo
  raw?: Record<string, unknown>
}

export async function fetchPaper(
  exe: string,
  identifier: string,
  outputDir: string,
  config: Config,
): Promise<FetchOutcome> {
  await mkdir(outputDir, { recursive: true })
  // 固定 OA 入口；调用方无机构模式参数。
  const r = await runScansci(
    exe,
    ['fetch', identifier, '--output', outputDir, '--format', 'json'],
    config,
    {
      timeoutMs: 10 * 60_000,
      useWrap: true,
      env: { SR_SCANSCI_DISABLE_INSTITUTION: '1' },
    },
  )
  const parsed = extractJson(r.stdout)
  if (!parsed) {
    return {
      status: 'manual_required',
      quality: 'none',
      reason: r.exitCode !== 0 ? 'scansci_fetch_failed' : 'unparseable_output',
      next_action: { kind: 'local_pdf', message: 'OA 获取不可用，请补入本地 PDF 后继续。' },
    }
  }
  const paper = parsed.paper as Record<string, unknown> | undefined
  const info: PaperInfo | undefined = paper
    ? {
        doi: String(paper.doi ?? ''),
        title: String(paper.title ?? ''),
        authors: Array.isArray(paper.authors) ? (paper.authors as string[]) : [],
        journal: String(paper.journal ?? ''),
        year: typeof paper.year === 'number' ? paper.year : null,
        source: String(paper.source ?? ''),
        url: String(paper.url ?? ''),
        pdf_path: String(paper.pdf_path ?? ''),
      }
    : undefined
  const nextAction = parsed.next_action as { kind: string; message: string; command?: string } | null | undefined
  return {
    status: String(parsed.status ?? 'unknown'),
    quality: String(parsed.quality ?? 'none'),
    reason: parsed.reason ? String(parsed.reason) : undefined,
    next_action: nextAction ?? null,
    paper: info,
    raw: parsed,
  }
}

// ── 机构登录 ──────────────────────────────────────────────────────

export async function loginScansci(
  exe: string,
  loginType: string,
  url?: string,
): Promise<RunResult> {
  return { exitCode: 1, stdout: '', stderr: 'oa_only_operation_not_supported' }
}

export async function setSchoolScansci(exe: string, school: string): Promise<RunResult> {
  return { exitCode: 1, stdout: '', stderr: 'oa_only_operation_not_supported' }
}

export async function defaultDownloadDir(): Promise<string> {
  return join(homedir(), 'scientific-reading-data', 'downloads')
}
// ── scientific-reading 引擎适配器（Phase 1：本地文献库）───────────────

function engineVenvPython(dataRoot: string): string {
  return process.platform === 'win32'
    ? join(dataRoot, '.venv', 'Scripts', 'python.exe')
    : join(dataRoot, '.venv', 'bin', 'python')
}

export async function ensureBundledEngine(config: Config): Promise<{ ok: boolean; python: string; detail: string }> {
  const dataRoot = resolveDataRoot(config)
  const venvPython = engineVenvPython(dataRoot)
  const wheelDir = fileURLToPath(new URL('../dist/python/', import.meta.url))
  let wheels: string[] = []
  try { wheels = (await readdir(wheelDir)).filter((name) => name.endsWith('.whl')) } catch { /* handled below */ }
  if (wheels.length !== 1) return { ok: false, python: venvPython, detail: 'bundled_engine_wheel_missing' }
  try { await access(venvPython) } catch {
    await mkdir(dataRoot, { recursive: true })
    const created = await runCommand(config.python, ['-m', 'venv', join(dataRoot, '.venv')], { timeoutMs: 120_000 })
    if (created.exitCode !== 0) return { ok: false, python: venvPython, detail: created.stderr || 'engine_venv_failed' }
  }
  const installed = await runCommand(
    venvPython,
    ['-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', join(wheelDir, wheels[0])],
    { timeoutMs: 180_000 },
  )
  if (installed.exitCode !== 0) return { ok: false, python: venvPython, detail: installed.stderr || 'engine_install_failed' }
  const probe = await runCommand(venvPython, ['-c', 'import scientific_reading'], { timeoutMs: 15_000 })
  return { ok: probe.exitCode === 0, python: venvPython, detail: probe.stderr || (probe.exitCode === 0 ? 'ready' : 'engine_probe_failed') }
}

/** 解析内置引擎 Python：显式开发覆盖 → 数据目录虚拟环境。 */
export async function resolveEnginePython(config: Config): Promise<string | null> {
  if (config.enginePython.trim()) {
    try { await access(config.enginePython.trim()); return config.enginePython.trim() } catch { /* fallthrough */ }
  }
  const bundled = engineVenvPython(resolveDataRoot(config))
  try {
    await access(bundled)
    const probe = await runCommand(bundled, ['-c', 'import scientific_reading'], { timeoutMs: 15_000 })
    if (probe.exitCode === 0) return bundled
  } catch { /* setup 尚未执行 */ }
  return null
}

/** 运行引擎 CLI：python -m scientific_reading --data-root <dataRoot> ... */
export async function runEngine(
  config: Config,
  args: string[],
  opts: { timeoutMs?: number; env?: NodeJS.ProcessEnv; input?: string } = {},
): Promise<{ ok: boolean; exitCode: number; stdout: string; stderr: string; json: Record<string, unknown> | null }> {
  const python = await resolveEnginePython(config)
  if (!python) {
    return {
      ok: false,
      exitCode: 1,
      stdout: '',
      stderr: '未找到 scientific-reading 引擎（请配置 enginePython 或先运行 sr_setup 安装引擎）',
      json: null,
    }
  }
  const dataRoot = resolveDataRoot(config)
  const r = await runCommand(python, ['-m', 'scientific_reading', '--data-root', dataRoot, ...args], {
    timeoutMs: opts.timeoutMs ?? 60_000,
    ...(opts.input !== undefined ? { input: opts.input } : {}),
    env: { ...opts.env, ...engineScopeEnvironment() },
  })
  const parsed = extractJson(r.stdout)
  // 0=成功；2=user gate；3=agent gate；job-status 对 failed/interrupted 也返回协议 JSON
  const jobStatus = args[0] === 'job-status' && typeof parsed?.job_id === 'string'
  const gateOk = r.exitCode === 0 || r.exitCode === 2 || r.exitCode === 3 || jobStatus
  return { ok: gateOk, exitCode: r.exitCode, stdout: r.stdout, stderr: r.stderr, json: parsed }
}

/** 运行引擎并解析 JSON；input 通过 UTF-8 stdin 传入，避免把元数据拼进命令行。 */
export async function engineJson(
  config: Config,
  args: string[],
  input?: unknown,
  env?: NodeJS.ProcessEnv,
): Promise<{ ok: boolean; exitCode: number; stdout: string; stderr: string; json: Record<string, unknown> | null }> {
  const encoded = input === undefined ? undefined : JSON.stringify(input)
  return runEngine(config, args, {
    ...(encoded === undefined ? {} : { input: encoded }),
    ...(env ? { env } : {}),
  })
}

/** 启动不等待结果的引擎子进程。子进程只继承宿主环境，不把环境值写入日志。 */
export async function engineStartDetached(
  config: Config,
  args: string[],
  input?: unknown,
): Promise<{ started: boolean; detail?: string }> {
  const python = await resolveEnginePython(config)
  if (!python) return { started: false, detail: 'engine_not_found' }
  const dataRoot = resolveDataRoot(config)
  let child: ReturnType<typeof spawn>
  try {
    child = spawn(
      python,
      ['-m', 'scientific_reading', '--data-root', dataRoot, ...args],
      {
        detached: true,
        windowsHide: true,
        stdio: ['pipe', 'ignore', 'ignore'],
        env: {
          ...process.env,
          TERM: 'dumb',
          NO_COLOR: '1',
          PYTHONIOENCODING: 'utf-8',
          ...engineScopeEnvironment(),
        },
      },
    )
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    return { started: false, detail: typeof code === 'string' ? code : 'spawn_failed' }
  }
  return await new Promise((resolve) => {
    let settled = false
    const finish = (result: { started: boolean; detail?: string }): void => {
      if (settled) return
      settled = true
      resolve(result)
    }
    child.once('spawn', () => {
      if (input !== undefined) child.stdin?.end(JSON.stringify(input))
      else child.stdin?.end()
      child.unref()
      finish({ started: true })
    })
    child.once('error', (error: NodeJS.ErrnoException) => {
      finish({ started: false, detail: typeof error.code === 'string' ? error.code : 'spawn_failed' })
    })
  })
}

/** 持久派生编排：引擎负责记录 pending/failed 状态，插件只提交一次。 */
export async function engineDerivedEnqueue(config: Config, paperId: string): Promise<{ ok: boolean; json: Record<string, unknown> | null; stderr: string }> {
  const args = ['derived-enqueue', '--paper-id', paperId]
  const r = await engineJson(config, args)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

/** Abstract agent gate：只提交 agent 提供的翻译，不自动生成或伪造翻译。 */
export async function engineAbstractReadSubmit(config: Config, jobId: string, abstractTranslation: unknown): Promise<{ ok: boolean; json: Record<string, unknown> | null; stderr: string }> {
  const r = await engineJson(config, ['abstract-read-submit', '--job-id', jobId, '--input', '-'], abstractTranslation)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

/** 两阶段入库：先执行本地事务，派生阶段由调用方提交一次持久 derived-enqueue。 */
export async function engineLibraryIngest(config: Config, input: unknown): Promise<{ ok: boolean; json: Record<string, unknown> | null; stderr: string }> {
  const r = await engineJson(config, ['library-ingest'], input)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

/** library-list-v2：分页、查询、文件夹、标签和状态筛选。 */
export async function engineLibraryList(config: Config, options: {
  page?: number; pageSize?: number; query?: string; folder?: string; tags?: string[]; status?: string
} = {}): Promise<{ ok: boolean; json: unknown; stderr: string }> {
  const args = ['library-list-v2', '--page', String(options.page ?? 1), '--page-size', String(options.pageSize ?? 50)]
  if (options.query) args.push('--query', options.query)
  if (options.folder) args.push('--folder-id', options.folder)
  for (const tag of options.tags ?? []) args.push('--tag', tag)
  if (options.status) args.push('--status', options.status)
  const r = await engineJson(config, args)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

/** library-item-v2：按主库 paper_id 读取摘要与派生状态。 */
export async function engineLibraryItem(config: Config, paperId: string): Promise<{ ok: boolean; json: Record<string, unknown> | null; stderr: string }> {
  const r = await engineJson(config, ['library-item-v2', '--paper-id', paperId])
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineFolderManage(config: Config, args: string[]): Promise<{ ok: boolean; json: unknown; stderr: string }> {
  const r = await engineJson(config, args)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineClassification(config: Config, command: 'classification-apply' | 'classification-undo', input?: unknown, operationId?: string): Promise<{ ok: boolean; json: unknown; stderr: string }> {
  const args: string[] = [command]
  if (command === 'classification-apply') args.push('--input', '-')
  else args.push('--operation-id', operationId ?? '')
  const r = await engineJson(config, args, input)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

/** library-ensure：写入本地文献库条目（查重+读回） */
export async function engineJobStatus(config: Config, jobId: string): Promise<{ ok: boolean; json: Record<string, unknown> | null; stderr: string }> {
  const r = await runEngine(config, ['job-status', '--job-id', jobId])
  const states = new Set(['queued', 'running', 'waiting_user', 'waiting_agent', 'interrupted', 'failed', 'completed'])
  const validStatus = r.json?.job_id === jobId && states.has(String(r.json?.status))
  return { ok: r.ok || validStatus, json: r.json, stderr: r.stderr }
}

async function trustedProviderEnv(config: Config): Promise<NodeJS.ProcessEnv> {
  const sanitized: NodeJS.ProcessEnv = { SR_SCANSCI_DISABLE_INSTITUTION: '1' }
  const python = await resolveScansciPython(config)
  if (!python) return sanitized
  const wrapper = wrapScriptPath()
  try { await access(wrapper) } catch { return sanitized }
  await ensureScansciConfig({ ...config, legalOnly: true })
  return {
    ...sanitized,
    SR_SCANSCI_PROVIDER_PYTHON: python,
    SR_SCANSCI_PROVIDER_WRAPPER: wrapper,
  }
}

export async function engineStartFullRead(config: Config, paperId: string) {
  const env = await trustedProviderEnv(config)
  const providerProfile = env.SR_SCANSCI_PROVIDER_WRAPPER ? 'scansci' : 'none'
  const r = await engineJson(
    config,
    ['full-read-pipeline-start', '--paper-id', paperId, '--provider-profile', providerProfile],
    undefined,
    env,
  )
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineContinueFullRead(config: Config, jobId: string, suppliedInput: Record<string, unknown>) {
  const env = await trustedProviderEnv(config)
  const r = await engineJson(config, ['full-read-pipeline-resume', '--job-id', jobId, '--input', '-'], suppliedInput, env)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineAttachAndResumeFullReadPdf(config: Config, paperId: string, jobId: string, pdfPath: string) {
  const env = await trustedProviderEnv(config)
  const r = await engineJson(config, ['full-read-pdf-attach-resume', '--paper-id', paperId, '--job-id', jobId, '--pdf', pdfPath], undefined, env)
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineAttachLibraryPdf(config: Config, paperId: string, pdfPath: string) {
  const r = await engineJson(config, ['pdf-attach-library', '--paper-id', paperId, '--pdf', pdfPath])
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineExportAssets(config: Config, paperId: string) {
  const r = await engineJson(config, ['export-assets', '--paper-id', paperId])
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineResolveArtifact(config: Config, paperId: string, kind: 'pdf' | 'reader' | 'exports') {
  const r = await engineJson(config, ['artifact-resolve', '--paper-id', paperId, '--kind', kind])
  return { ok: r.ok, json: r.json, stderr: r.stderr }
}

export async function engineReviewOpenState(config: Config, parentSessionId: string, paperId: string) {
  return engineJson(config, ['review-session-get'], {
    parent_session_id: parentSessionId,
    paper_id: paperId,
  })
}

export async function engineReviewBind(config: Config, parentSessionId: string, paperId: string, reviewSessionId: string) {
  return engineJson(config, ['review-session-bind'], {
    parent_session_id: parentSessionId,
    paper_id: paperId,
    review_session_id: reviewSessionId,
  })
}

export async function engineReviewContext(config: Config, reviewSessionId: string) {
  return engineJson(config, ['review-context'], { review_session_id: reviewSessionId })
}

export async function engineReviewConfirm(config: Config, reviewSessionId: string, conclusions: unknown[]) {
  return engineJson(config, ['review-confirm'], {
    review_session_id: reviewSessionId,
    conclusions,
  })
}

export async function engineXlsxRefresh(config: Config) {
  return engineJson(config, ['xlsx-refresh'], {})
}
/** library-ensure --check：只读查重 */
