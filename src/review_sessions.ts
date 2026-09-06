import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Context } from 'cordis'
import type { Config } from './config.js'
import { engineReviewBind, engineReviewOpenState } from './cli.js'
import { isPaperId } from './papers.js'

const JSON_LIMIT = 16 * 1024

interface ParentAgentLike {
  id: string
  session: { header: { id: string; agentPreset?: string } }
}

interface ReviewStartSpec {
  provider: 'fork'
  label: string
  request: { prompt: Array<{ type: 'text'; text: string }>; parent: ParentAgentLike }
  signal: AbortSignal
}

interface ReviewBinding {
  status: string
  parent_session_id: string
  paper_id: string
  review_session_id: string
}

interface ReviewOpenState {
  status: string
  parent_session_id: string
  paper_id: string
  title: string
  review_session_id?: string
}

export interface ReviewSessionDependencies {
  readState(parentSessionId: string, paperId: string): Promise<ReviewOpenState>
  getParent(parentSessionId: string): ParentAgentLike | undefined
  startContinuable(spec: ReviewStartSpec): Promise<{ childId: string; messageId: string }>
  bind(parentSessionId: string, paperId: string, reviewSessionId: string): Promise<ReviewBinding>
}

export interface ReviewSessionOpenResult {
  status: 'created' | 'reused'
  parent_session_id: string
  paper_id: string
  review_session_id: string
  mode: 'continuable'
}

function requireSessionId(value: string): void {
  if (!value.trim() || value.length > 256 || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error('parent_session_id_invalid')
  }
}

function reviewPrompt(title: string, parentSessionId: string, paperId: string): string {
  return [
    '这是一个附属于父会话的单篇论文整理子会话。',
    `论文：${title}`,
    `paper_id：${paperId}`,
    `父会话分类：${parentSessionId}`,
    '',
    '请先调用 sr_review_context 读取本论文已有资产和确认结论，然后主动提出候选关键结论。',
    '每条候选结论必须列出结论类型、结论正文和可核对的证据位置；无法定位时明确说明。',
    '候选内容尚未入库。请与用户讨论、修订，只有在用户明确确认当前版本需要入库后，才可调用 sr_review_confirm。',
  ].join('\n')
}

export function createReviewSessionOpener(deps: ReviewSessionDependencies, presetId: string) {
  const inFlight = new Map<string, Promise<ReviewSessionOpenResult>>()

  async function createOrReuse(
    parentSessionId: string,
    paperId: string,
    signal: AbortSignal,
  ): Promise<ReviewSessionOpenResult> {
    const state = await deps.readState(parentSessionId, paperId)
    if (state.status === 'bound' && typeof state.review_session_id === 'string') {
      return {
        status: 'reused',
        parent_session_id: parentSessionId,
        paper_id: paperId,
        review_session_id: state.review_session_id,
        mode: 'continuable',
      }
    }
    if (state.status !== 'missing' || !state.title.trim()) throw new Error('review_state_invalid')
    const parent = deps.getParent(parentSessionId)
    if (!parent) throw new Error('parent_session_not_live')
    if (parent.session.header.agentPreset !== presetId) throw new Error('parent_not_literature_session')
    const started = await deps.startContinuable({
      provider: 'fork',
      label: state.title,
      request: {
        prompt: [{ type: 'text', text: reviewPrompt(state.title, parentSessionId, paperId) }],
        parent,
      },
      signal,
    })
    const binding = await deps.bind(parentSessionId, paperId, started.childId)
    return {
      status: binding.status === 'created' ? 'created' : 'reused',
      parent_session_id: parentSessionId,
      paper_id: paperId,
      review_session_id: binding.review_session_id,
      mode: 'continuable',
    }
  }

  return {
    open(parentSessionId: string, paperId: string, signal: AbortSignal = new AbortController().signal): Promise<ReviewSessionOpenResult> {
      requireSessionId(parentSessionId)
      if (!isPaperId(paperId)) return Promise.reject(new Error('paper_id_invalid'))
      const key = JSON.stringify([parentSessionId, paperId])
      const current = inFlight.get(key)
      if (current) return current
      const task = createOrReuse(parentSessionId, paperId, signal)
      inFlight.set(key, task)
      void task.finally(() => { if (inFlight.get(key) === task) inFlight.delete(key) }).catch(() => {})
      return task
    },
  }
}

interface ReviewHostServices {
  agents: { get(id: string): ParentAgentLike | undefined }
  subagents: { startContinuable(spec: ReviewStartSpec): Promise<{ childId: string; messageId: string }> }
}

function hostDependencies(ctx: Context, config: Config): ReviewSessionDependencies {
  const host = ctx as unknown as ReviewHostServices
  return {
    async readState(parentSessionId, paperId) {
      const result = await engineReviewOpenState(config, parentSessionId, paperId)
      if (!result.ok || !result.json) throw new Error('review_state_unavailable')
      return result.json as unknown as ReviewOpenState
    },
    getParent(parentSessionId) { return host.agents.get(parentSessionId) },
    startContinuable(spec) { return host.subagents.startContinuable(spec) },
    async bind(parentSessionId, paperId, reviewSessionId) {
      const result = await engineReviewBind(config, parentSessionId, paperId, reviewSessionId)
      if (!result.ok || !result.json) throw new Error('review_binding_failed')
      return result.json as unknown as ReviewBinding
    },
  }
}

function sendJson(res: ServerResponse, status: number, value: unknown): void {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(JSON.stringify(value))
}

function sameOrigin(req: IncomingMessage): boolean {
  const origin = req.headers.origin
  const host = req.headers.host
  if (typeof origin !== 'string' || typeof host !== 'string' || req.headers['x-sr-csrf'] !== '1') return false
  try { return new URL(origin).host === host } catch { return false }
}

function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = []
    let size = 0
    req.on('data', (chunk: Buffer) => {
      size += chunk.length
      if (size > JSON_LIMIT) { reject(new Error('body_too_large')); req.destroy() } else chunks.push(chunk)
    })
    req.on('end', () => {
      try {
        const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('invalid_json')
        resolve(parsed as Record<string, unknown>)
      } catch { reject(new Error('invalid_json')) }
    })
  })
}

export function registerReviewSessionRoutes(
  ctx: Context,
  config: Pick<Config, 'presetId'>,
  suppliedOpener?: ReturnType<typeof createReviewSessionOpener>,
): void {
  const opener = suppliedOpener ?? createReviewSessionOpener(hostDependencies(ctx, config as Config), config.presetId)
  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: '/sr/api/reviews/open',
    async handler(req: IncomingMessage, res: ServerResponse) {
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
      if (!sameOrigin(req)) return sendJson(res, 403, { error: 'request_forbidden' })
      try {
        const body = await readJson(req)
        if (setOf(body).size !== 2 || typeof body.parent_session_id !== 'string' || typeof body.paper_id !== 'string') {
          return sendJson(res, 400, { error: 'review_request_invalid' })
        }
        sendJson(res, 200, await opener.open(body.parent_session_id, body.paper_id))
      } catch (error) {
        const code = error instanceof Error ? error.message : 'review_open_failed'
        const status = code === 'body_too_large' ? 413 : code.endsWith('_invalid') ? 400 : 409
        sendJson(res, status, { error: code })
      }
    },
  }), 'sr-route:/sr/api/reviews/open')
}

function setOf(value: Record<string, unknown>): Set<string> {
  return new Set(Object.keys(value))
}
