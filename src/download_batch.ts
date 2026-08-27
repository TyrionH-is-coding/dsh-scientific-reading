import { randomUUID } from 'node:crypto'
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Config } from './config.js'
import { resolveDataRoot, resolveOutputDir } from './config.js'
import { engineAttachLibraryPdf, engineLibraryItem, engineResolveArtifact, fetchPaper, loginScansci } from './cli.js'

type FetchResult = { status: string; pdfPath?: string }
type Child = { paperId: string; status: string; phase?: string }
export type DownloadDeps = {
  loadPaper(id: string): Promise<Record<string, unknown> | undefined>
  hasPdf(id: string): Promise<boolean>
  directFetch(id: string, paper: Record<string, unknown>): Promise<FetchResult>
  openInstitutionSession(): Promise<{ status: string }>
  institutionFetch(id: string, paper: Record<string, unknown>): Promise<FetchResult>
  attachPdf(id: string, path: string): Promise<{ status: string }>
}

function summarize(children: Child[]) {
  const summary: Record<string, number> = { total: children.length, completed: 0, skipped_existing: 0, anti_automation_challenge: 0, manual_required: 0, failed: 0 }
  for (const child of children) summary[child.status] = (summary[child.status] ?? 0) + 1
  return summary
}

export async function runDownloadBatch(selection: string[], deps: DownloadDeps) {
  if (!Array.isArray(selection) || selection.length === 0) throw new Error('download_batch_selection_required')
  if (selection.length > 100) throw new Error('download_batch_too_large')
  const ids = [...new Set(selection)]
  const papers = new Map<string, Record<string, unknown>>()
  const children = new Map<string, Child>()
  const directCandidates: string[] = []
  for (const id of ids) {
    const paper = await deps.loadPaper(id)
    if (!paper) { children.set(id, { paperId: id, status: 'failed' }); continue }
    papers.set(id, paper)
    if (await deps.hasPdf(id)) children.set(id, { paperId: id, status: 'skipped_existing' })
    else directCandidates.push(id)
  }
  const remaining: string[] = []
  await Promise.all(directCandidates.map(async (id) => {
    try {
      const result = await deps.directFetch(id, papers.get(id)!)
      if (result.status === 'completed' && result.pdfPath) {
        const attached = await deps.attachPdf(id, result.pdfPath)
        children.set(id, { paperId: id, status: attached.status === 'completed' ? 'completed' : 'failed', phase: 'direct' })
      } else if (result.status === 'anti_automation_challenge') {
        children.set(id, { paperId: id, status: 'anti_automation_challenge', phase: 'direct' })
      } else remaining.push(id)
    } catch { remaining.push(id) }
  }))
  if (remaining.length) {
    let sessionReady = false
    try { sessionReady = (await deps.openInstitutionSession()).status === 'ready' } catch { sessionReady = false }
    for (const id of remaining) {
      if (!sessionReady) { children.set(id, { paperId: id, status: 'manual_required', phase: 'institution' }); continue }
      try {
        const result = await deps.institutionFetch(id, papers.get(id)!)
        if (result.status === 'completed' && result.pdfPath) {
          const attached = await deps.attachPdf(id, result.pdfPath)
          children.set(id, { paperId: id, status: attached.status === 'completed' ? 'completed' : 'failed', phase: 'institution' })
        } else {
          children.set(id, { paperId: id, status: result.status === 'anti_automation_challenge' ? 'anti_automation_challenge' : 'manual_required', phase: 'institution' })
        }
      } catch { children.set(id, { paperId: id, status: 'failed', phase: 'institution' }) }
    }
  }
  const ordered = ids.map((id) => children.get(id) ?? { paperId: id, status: 'failed' })
  return {
    status: 'completed',
    children: ordered,
    summary: summarize(ordered),
    challengePaperIds: ordered.filter((child) => child.status === 'anti_automation_challenge').map((child) => child.paperId),
  }
}

function identifier(paper: Record<string, unknown>): string {
  for (const key of ['doi', 'pmid', 'source_url', 'title']) {
    if (typeof paper[key] === 'string' && paper[key].trim()) return paper[key].trim()
  }
  return ''
}

async function persist(dataRoot: string, jobId: string, value: unknown): Promise<void> {
  const directory = join(dataRoot, 'jobs', 'downloads')
  await mkdir(directory, { recursive: true })
  const target = join(directory, jobId + '.json')
  const temporary = target + '.tmp'
  await writeFile(temporary, JSON.stringify(value, null, 2) + '\n', 'utf8')
  await rename(temporary, target)
}

export async function submitDownloadBatch(config: Config, selection: string[]) {
  if (!selection.length || selection.length > 100) throw new Error(selection.length ? 'download_batch_too_large' : 'download_batch_selection_required')
  const jobId = 'job_' + randomUUID().replaceAll('-', '').slice(0, 16)
  const dataRoot = resolveDataRoot(config)
  await persist(dataRoot, jobId, { parent_job_id: jobId, status: 'queued', selection })
  queueMicrotask(() => {
    void (async () => {
      await persist(dataRoot, jobId, { parent_job_id: jobId, status: 'running', selection })
      const result = await runDownloadBatch(selection, {
        async loadPaper(id) {
          const result = await engineLibraryItem(config, id)
          return result.ok && result.json ? result.json : undefined
        },
        async hasPdf(id) { return (await engineResolveArtifact(config, id, 'pdf')).ok },
        async directFetch(id, paper) {
          const value = identifier(paper)
          if (!value) return { status: 'remaining' }
          const output = join(resolveOutputDir(config), '.batch', jobId, id)
          const outcome = await fetchPaper(config.scansciExe, value, output, config, { suppressBrowserLogin: true })
          return outcome.status === 'success' && outcome.paper?.pdf_path ? { status: 'completed', pdfPath: outcome.paper.pdf_path } : { status: 'remaining' }
        },
        async openInstitutionSession() {
          if (!config.school.trim()) return { status: 'unavailable' }
          const login = await loginScansci(config.scansciExe, config.loginType)
          return { status: login.exitCode === 0 ? 'ready' : 'unavailable' }
        },
        async institutionFetch(id, paper) {
          const value = identifier(paper)
          if (!value) return { status: 'manual_required' }
          const output = join(resolveOutputDir(config), '.batch', jobId, id)
          const outcome = await fetchPaper(config.scansciExe, value, output, config, { suppressBrowserLogin: true })
          if (outcome.status === 'success' && outcome.paper?.pdf_path) return { status: 'completed', pdfPath: outcome.paper.pdf_path }
          const detail = `${outcome.reason ?? ''} ${outcome.next_action?.kind ?? ''}`
          return /anti.?automation|captcha|challenge/i.test(detail) ? { status: 'anti_automation_challenge' } : { status: 'manual_required' }
        },
        async attachPdf(id, path) {
          const result = await engineAttachLibraryPdf(config, id, path)
          return { status: result.ok ? 'completed' : 'failed' }
        },
      })
      await persist(dataRoot, jobId, { parent_job_id: jobId, ...result })
    })().catch(async () => { await persist(dataRoot, jobId, { parent_job_id: jobId, status: 'failed' }).catch(() => {}) })
  })
  return { parent_job_id: jobId, status: 'queued' }
}

export async function readDownloadJob(config: Config, jobId: string): Promise<Record<string, unknown> | null> {
  if (!/^job_[0-9a-f]{16}$/.test(jobId)) return null
  try {
    const value = JSON.parse(await readFile(join(resolveDataRoot(config), 'jobs', 'downloads', jobId + '.json'), 'utf8'))
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null
  } catch { return null }
}
