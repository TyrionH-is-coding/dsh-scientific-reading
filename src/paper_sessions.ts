import { createHash, randomUUID } from 'node:crypto'
import { readFile, realpath } from 'node:fs/promises'
import { extname, isAbsolute, join, relative } from 'node:path'
import type { Context } from 'cordis'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { engineJson } from './cli.js'
import { resolveDataRoot, type Config } from './config.js'
import { withEngineScope, withoutEngineScope, type EngineScope } from './engine_scope.js'
import { readJson, sameOrigin, sendJson } from './review_sessions.js'

type Engine = (args: string[], input?: unknown) => Promise<any>
type Rpc = (method: string, payload: Record<string, unknown>) => Promise<any>
export const PAPER_TOOLS = new Set(['sr_model_step', 'sr_abstract_submit', 'sr_library_list', 'sr_start_full_read',
  'sr_continue_full_read', 'sr_export_assets', 'sr_job_status', 'sr_evidence_locate',
  'sr_review_context', 'sr_review_confirm', 'sr_paper_context', 'sr_read_job_input', 'sr_research_submit', 'csr_read_job_input'])

export function configEngine(config: Config): Engine {
  return async (args, input) => {
    const result = await engineJson(config, args, input)
    if (!result.ok || !result.json) throw new Error(String(result.json?.error || 'engine_request_failed'))
    return result.json
  }
}

// Host plugins use the public Gateway so strict argument validation and service lifetimes remain owned by DSH.
export function createNativeRpc(ctx: Context) {
  return async (method: string, payload: Record<string, any>, requestId = randomUUID()): Promise<any> => {
    const gateway = (ctx as any).typertGateway
    const signal = AbortSignal.timeout(30000)
    if (method === 'session.history') {
      const address = {kind:'session', sessionId:payload.sessionId}
      const stream = await gateway.stream({namespace:'session', method:'follow', args:{request:{address,maxMessages:payload.maxMessages}}, signal})
      const iterator = stream[Symbol.asyncIterator]()
      let opening: any
      try { opening = (await iterator.next()).value } finally { await iterator.return?.() }
      if (opening?.type !== 'snapshot') throw new Error('native_history_invalid')
      const page = payload.beforeSeq === undefined ? opening : await gateway.invoke({namespace:'session',method:'page',
        args:{request:{address,throughSeq:opening.cursor,beforeSeq:payload.beforeSeq,maxMessages:payload.maxMessages}},signal})
      return {events:page.records,hasMore:page.hasMore}
    }
    const [namespace, name] = method.split('.')
    const request = method === 'session.prompt' ? {...payload,requestId} : payload
    const args = method === 'settings.describe' ? {} : namespace === 'settings' ? payload : method === 'session.list' ? {_request:request} : {request}
    return gateway.invoke({namespace,method:name,args,signal})
  }
}

export async function nativeRpc(url: string, method: string, payload: Record<string, unknown>) {
  const rpcId = randomUUID()
  const response = await fetch(`${url}/api/${method}`, { method: 'POST', signal: AbortSignal.timeout(30000),
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'client-request', rpcId, method, payload }) })
  const reply = await response.json() as any
  if (!response.ok || reply.type !== 'server-response' || reply.rpcId !== rpcId || reply.result?.ok !== true) {
    throw new Error('native_session_request_failed')
  }
  return reply.result.value
}

export async function readPaperJobInput(dataRoot: string, engine: Engine, args: any) {
  if (!['source_manifest_path', 'translations_json'].includes(args.field) || !/^job_[a-f0-9]{16}$/.test(args.job_id ?? '')) throw new Error('invalid_job_input')
  const offset = args.offset ?? 0, limit = args.limit ?? 20000
  if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 50000) throw new Error('invalid_page')
  const job = await engine(['job-status', '--job-id', args.job_id])
  const gate = job.detail?.required_input, requested = gate?.[args.field]
  if (typeof requested !== 'string') throw new Error('job_input_unavailable')
  const papers = await realpath(join(dataRoot, 'papers'))
  const paper = await realpath(join(papers, job.paper_id)), file = await realpath(requested)
  for (const [root, target] of [[papers, paper], [paper, file]]) {
    const rel = relative(root, target)
    if (!rel || rel.startsWith('..') || isAbsolute(rel)) throw new Error('job_input_outside_paper')
  }
  if (extname(file) !== '.json') throw new Error('job_input_invalid')
  const raw = await readFile(file)
  let text = raw.toString('utf8')
  if (args.field === 'source_manifest_path' && gate.submission_contract_version === 'full-translation-v4') {
    if (createHash('sha256').update(raw).digest('hex') !== gate.batch_sha256) throw new Error('job_input_changed')
    const source = JSON.parse(text), remaining = gate.remaining_block_ids
    if (source.batch_id !== gate.batch_id || source.source_sha256 !== gate.source_sha256 || !Array.isArray(source.blocks) ||
      !Array.isArray(remaining) || !remaining.length || new Set(remaining).size !== remaining.length) throw new Error('job_input_invalid')
    const blocks = source.blocks.filter((block: any) => remaining.includes(block.block_id))
    if (JSON.stringify(blocks.map((block: any) => block.block_id)) !== JSON.stringify(remaining)) throw new Error('job_input_invalid')
    text = JSON.stringify({ ...source, translation_contract_version: gate.submission_contract_version, batch_sha256: gate.batch_sha256, accepted_blocks: gate.accepted_blocks, blocks }, null, 2)
  }
  const current = await engine(['job-status', '--job-id', args.job_id])
  if (JSON.stringify(current.detail?.required_input) !== JSON.stringify(gate)) throw new Error('job_gate_changed')
  return { job_id: args.job_id, field: args.field, offset, total: text.length,
    text: text.slice(offset, offset + limit), nextOffset: offset + limit < text.length ? offset + limit : null }
}

/** Public conversation text and tool evidence, excluding internal reasoning and hidden prompts. */
export function conversationEvents(entries: any[]) {
  return entries.flatMap(({ event }) => {
    if (!event || (event.surfaceOp && event.surfaceOp !== 'append')) return []
    if (!['user/message', 'assistant/message', 'tool/result'].includes(event.type)) return []
    const message = event.type === 'user/message' ? event.data : event.data?.message
    if (event.type === 'user/message' && message?.source?.kind !== 'user') return []
    const content = (message?.content || []).flatMap((part: any) => part.type === 'tool-result' ? part.content || [] : [part])
      .filter((part: any) => ['text', 'image', 'image_ref'].includes(part.type))
      .map((part: any) => part.type === 'text' ? { type: 'text', text: part.text }
        : { type: part.type, attachmentId: part.attachmentId ?? part.attachment?.id ?? null, imageNotRead: true })
    if (!content.length) return []
    return [{ seq: event.seq, time: event.time, role: event.type.split('/')[0], content,
      evidence_status: event.type === 'tool/result' ? 'tool_output_requires_source_check' : 'discussion_not_paper_fact' }]
  })
}

/** Pin pages by beforeSeq and SHA so a long read cannot combine different revisions. */
export async function readSelectedChats(engine: Engine, rpc: Rpc, request: any) {
  const { selection, question, maxMessages = 40, maxChars = 24000 } = request
  if (!Array.isArray(selection) || !selection.length || selection.length > 20 || selection.some(row => !row || typeof row !== 'object') ||
    new Set(selection.map(row => row.paper_id)).size !== selection.length ||
    typeof question !== 'string' || !question.trim() || question.length > 8000 ||
    !Number.isInteger(maxMessages) || maxMessages < 1 || maxMessages > 100 ||
    !Number.isInteger(maxChars) || maxChars < 100 || maxChars > 100000) throw new Error('chat_selection_invalid')
  const states = []
  for (const selected of selection) {
    if (typeof selected.paper_id !== 'string' ||
      (selected.beforeSeq !== undefined && (!Number.isInteger(selected.beforeSeq) || selected.beforeSeq < 0)) ||
      (selected.textOffset !== undefined && (!Number.isInteger(selected.textOffset) || selected.textOffset < 0)) ||
      (selected.textOffset > 0 && (selected.beforeSeq === undefined || typeof selected.pageSha256 !== 'string'))) throw new Error('chat_cursor_invalid')
    const state = await engine(['paper-chat'], { action: 'get', paper_id: selected.paper_id })
    if (!state.session_id) throw new Error('paper_chat_missing')
    states.push(state)
  }
  const chats = []
  for (let i = 0; i < selection.length; i++) {
    const selected = selection[i], state = states[i]
    const history = await rpc('session.history', { sessionId: state.session_id, maxMessages,
      ...(selected.beforeSeq !== undefined ? { beforeSeq: selected.beforeSeq } : {}) })
    if (!Array.isArray(history.events) || typeof history.hasMore !== 'boolean') throw new Error('native_history_invalid')
    const seqs = history.events.map((row: any) => row.event?.seq).filter(Number.isInteger)
    const text = JSON.stringify(conversationEvents(history.events))
    const pageSha256 = createHash('sha256').update(text).digest('hex')
    if (selected.pageSha256 && selected.pageSha256 !== pageSha256) throw new Error('chat_page_changed')
    const offset = selected.textOffset || 0
    if (offset > text.length) throw new Error('chat_cursor_invalid')
    const end = Math.min(offset + maxChars, text.length)
    chats.push({ ...state, history: { text: text.slice(offset, end), textOffset: offset, totalChars: text.length,
      nextTextOffset: end < text.length ? end : null, pageSha256, maxMessages,
      beforeSeq: selected.beforeSeq ?? (seqs.length ? Math.max(...seqs) + 1 : 0),
      nextBeforeSeq: history.hasMore && seqs.length ? Math.min(...seqs) : null,
      hasMore: history.hasMore, truncated: history.hasMore || offset > 0 || end < text.length,
      eventSeqRange: seqs.length ? [Math.min(...seqs), Math.max(...seqs)] : null,
      included: '用户正文、助手可见回答与工具证据；图片仅保留引用，未读取图像；不含内部推理或系统提示。' } })
  }
  return { question, selectedPaperIds: selection.map(row => row.paper_id), chats,
    instructions: '只综合本次所选文献。逐项注明 paper_id、session_id 与原文证据；区分论文结论、个人讨论和模型推断。明确未读取的历史与图像范围，不以聊天代替原文。' }
}

export async function readLegacyChat(engine: Engine, rpc: Rpc, request: any) {
  const registry = await engine(['paper-chat'], {action:'legacy_list'})
  const entry = [...registry.sessions, ...(registry.reviews || [])].find(row => row.session_id === request.session_id)
  if (!entry) throw new Error('legacy_chat_unregistered')
  const before = request.beforeSeq, offset = request.textOffset ?? 0
  if ((before !== undefined && (!Number.isInteger(before) || before < 0)) || !Number.isInteger(offset) || offset < 0 ||
      (offset && (before === undefined || typeof request.pageSha256 !== 'string'))) throw new Error('chat_cursor_invalid')
  const result = await rpc('session.history', {sessionId:entry.session_id,maxMessages:40,...(before !== undefined ? {beforeSeq:before} : {})})
  if (!Array.isArray(result.events) || typeof result.hasMore !== 'boolean') throw new Error('native_history_invalid')
  const seqs = result.events.map((row: any) => row.event?.seq).filter(Number.isInteger)
  const text = conversationEvents(result.events).map(row => `[${row.seq} · ${row.role}]\n` + row.content.map((part: any) => part.type==='text' ? part.text : '[原消息含图像；本历史视图未读取图片]').join('\n')).join('\n\n')
  const sha = createHash('sha256').update(text).digest('hex')
  if ((request.pageSha256 && request.pageSha256 !== sha) || offset > text.length) throw new Error('chat_page_changed')
  return {...entry,read_only:true,text:text.slice(offset,offset+32000),totalChars:text.length,textOffset:offset,
    pageSha256:sha,beforeSeq:before ?? (seqs.length ? Math.max(...seqs)+1 : 0),
    nextTextOffset:offset+32000 < text.length ? offset+32000 : null,
    nextBeforeSeq:result.hasMore && seqs.length ? Math.min(...seqs) : null,
    truncated:result.hasMore || offset > 0 || offset+32000 < text.length,
    evidence_boundary:entry.origin==='v0.1-category' ? registry.evidence_boundary : '旧 Review 保留原论文关联；聊天内容仍须回查原文证据。'}
}

function figureLinks(context: any, origin: string) {
  if (!context || !origin) return context
  const absolute = (value: any) => typeof value === 'string' && value.startsWith('/sr/') ? new URL(value,origin).href : value
  return {...context,pdf_url:absolute(context.pdf_url),passages:context.passages?.map((row: any) =>
    ({...row,reader_url:absolute(row.reader_url),pdf_url:absolute(row.pdf_url)}))}
}

export async function discussFigure(engine: Engine, rpc: Rpc, request: any, origin = '') {
  const question = request.question || '请结合图片、图注和原文解释此图，区分可见事实、作者结论与推断。'
  if (typeof question !== 'string' || !question.trim() || question.length > 8000) throw new Error('figure_question_invalid')
  const selected = await engine(['paper-chat'], { ...request, action: 'figure_select' })
  const context = { ...figureLinks(selected.context,origin), image_status: selected.image ? 'attached_in_this_message' : 'text_only_not_supplied' }
  await rpc('session.prompt', { sessionId: selected.session_id, mode: 'queue', content: [
    { type: 'text', text: `当前 Figure 已切换为 ${context.asset_id}，上下文版本 ${context.revision}。此前选图不再是当前对象。\n${question}\n来源上下文：\n${JSON.stringify(context)}` },
    ...(selected.image ? [selected.image] : []),
  ] })
  const receipt = await engine(['paper-chat'], { action: 'figure_delivered', paper_id: request.paper_id,
    revision: context.revision, image_supplied: !!selected.image })
  return { session_id: selected.session_id, context: figureLinks(receipt,origin), chat_url: '/?sr-paper=' + encodeURIComponent(request.paper_id) }
}

export function registerPaperSessionRoutes(ctx: Context, config: Config) {
  const engine = configEngine(config)
  ctx.effect(() => ctx.webServer.register({kind:'exact', path:'/sr/api/views', async handler(req, res) {
    if (req.method !== 'POST') return sendJson(res, 405, {error:'method_not_allowed'})
    if (!sameOrigin(req)) return sendJson(res, 403, {error:'request_forbidden'})
    try {
      const body = await readJson(req, 512 * 1024)
      const folder = typeof body.scope_folder_id === 'string' && body.scope_folder_id ? ['--folder-id', body.scope_folder_id] : []
      const result = body.action === 'xlsx_refresh' ? await engine(['xlsx-refresh', ...folder])
        : body.action === 'xlsx_open' ? await engine(['xlsx-locate', '--paper-id', String(body.paper_id || ''), ...folder])
        : await engine(['library-views'], body)
      sendJson(res, 200, result)
    } catch (error) { sendJson(res, 400, {error:error instanceof Error ? error.message : 'library_view_failed'}) }
  }}), 'sr-library-views')
  const rpc: Rpc = createNativeRpc(ctx)
  ctx.on('system-prompt/assemble' as any, async (_assembly: any, context: any, next: any) => {
    const assembly = await next(), id = context.agent?.session?.id
    if (!id) return assembly
    const binding = await withoutEngineScope(() => engine(['paper-chat'], {action:'scope', session_id:id}))
    if (binding.legacy_read_only) return {...assembly,tools:[],sections:[...assembly.sections,{name:'sr-legacy-history',text:'此会话保留为旧历史，不再执行文献工具。继续阅读请打开相应论文的文献 chat。'}]}
    if (!binding.paper_id) return assembly
    const state = await withoutEngineScope(() => engine(['paper-chat'], {action:'get', paper_id:binding.paper_id}))
    state.active_figure = figureLinks(state.active_figure,`http://127.0.0.1:${(ctx.webServer as any).port}`)
    return { ...assembly, tools: assembly.tools.filter((tool: any) => PAPER_TOOLS.has(tool.name)),
      sections: [...assembly.sections, {name:'sr-paper-boundary', text:'本会话只负责当前绑定的单篇论文。每轮核对下面的最新上下文；新的 Figure 版本替代旧图。图片尚未提供时不能描述图像。区分图像事实、作者结论和推断并附原文定位。精读材料用 sr_read_job_input 按当前 job_id 分页读取，不能使用任意文件编辑器。'}],
      contexts: [...assembly.contexts, {name:'sr-current-paper', text:JSON.stringify(state)}] }
  })
  const pending = new Map<string, Promise<any>>()
  const figureQueue = new Map<string, Promise<any>>()
  const figure = (body: any) => {
    const key = String(body.paper_id || '')
    const prior = figureQueue.get(key) || Promise.resolve()
    const next = prior.catch(() => {}).then(async () => {
      await open(key)
      return discussFigure(engine, rpc, body,`http://127.0.0.1:${(ctx.webServer as any).port}`)
    })
    figureQueue.set(key, next)
    void next.finally(() => { if (figureQueue.get(key) === next) figureQueue.delete(key) }).catch(() => {})
    return next
  }
  const open = (paperId: string) => {
    if (pending.has(paperId)) return pending.get(paperId)!
    const promise = (async () => {
      const state = await engine(['paper-chat'], { action: 'ensure', paper_id: paperId })
      const existing = (await rpc('session.list', {})).items.find((row: any) => row.sessionId === state.session_id)
      const workspace = await rpc('workspace.create', { path: existing?.cwd || resolveDataRoot(config) })
      await rpc('session.create', { sessionId: state.session_id, workspaceId: workspace.workspace.workspaceId, agentPreset: config.presetId })
      await rpc('session.rename', { sessionId: state.session_id, title: '文献 · ' + state.paper.title })
      return state
    })()
    pending.set(paperId, promise)
    void promise.finally(() => pending.delete(paperId)).catch(() => {})
    return promise
  }
  for (const action of ['open', 'read', 'legacy', 'legacy-read', 'select', 'selection', 'figure']) {
    ctx.effect(() => ctx.webServer.register({ kind: 'exact', path: `/sr/api/chats/${action}`,
      async handler(req, res) {
        if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed' })
        if (!sameOrigin(req)) return sendJson(res, 403, { error: 'request_forbidden' })
        try {
          const body = await readJson(req, 64 * 1024)
          const result = action === 'open' ? await open(String(body.paper_id || ''))
            : action === 'figure' ? await figure(body)
            : action === 'read' ? await readSelectedChats(engine, rpc, body)
            : action === 'legacy-read' ? await readLegacyChat(engine, rpc, body)
            : action === 'select' ? await engine(['paper-chat'], { ...body, action: 'selection_save' })
            : await engine(['paper-chat'], { action: action === 'selection' ? 'selection_get' : 'legacy_list' })
          sendJson(res, 200, result)
        } catch (error) { sendJson(res, 400, { error: error instanceof Error ? error.message : 'chat_request_failed' }) }
      } }), `sr-chat:${action}`)
  }
  ctx.on('tools/execute', async (exec, next) => {
    const id = exec.agent?.session?.id
    if (!id) return next()
    const binding = await withoutEngineScope(() => engine(['paper-chat'], { action: 'scope', session_id: id }))
    if (binding.legacy_read_only) throw new Error('legacy_chat_read_only')
    if (!binding.paper_id) return next()
    if (!PAPER_TOOLS.has(exec.name)) throw new Error('paper_chat_tool_forbidden')
    const scope: EngineScope = { instanceId: resolveDataRoot(config), scopeSessionId: id, scopeFolderId: '__paper__', scopePaperId: binding.paper_id }
    return withEngineScope(scope, next)
  })
}

export function registerPaperTools(ctx: Context, config: Config) {
  ctx.effect(() => ctx.tools.register(defineTool({name:'sr_research_submit',
    description:'以 AI 来源填写本篇自定义研究字段。先读 sr_paper_context 的字段 ID、当前 revision 和摘要指纹；必须附原文定位或带 SHA 的摘要短引文。不能覆盖手动字段。',
    parameters:{field_id:{type:'string',required:true},value:{type:'string',required:true},expected_revision:{type:'number',required:true},evidence:{type:'json',required:true}},
    output:{schema:{type:'json'},render:(_args:unknown,value:unknown)=>[{type:'text' as const,text:JSON.stringify(value)}]},
    async execute(args, exec) {
      const engine = configEngine(config)
      const context = await engine(['paper-chat'], {action:'context_for_session',session_id:exec.agent?.session?.id})
      return await engine(['library-views'], {...args,action:'ai_set',paper_id:context.paper_id}) as never
    },
  })), 'sr_research_submit')
  ctx.effect(() => ctx.tools.register(defineTool({ name:'sr_read_job_input',
    description:'分页读取本篇精读任务当前 gate 指定的翻译源或复核材料，附剩余块范围。不能读取任意路径。',
    parameters:{job_id:{type:'string',required:true}, field:{type:'string',required:true}, offset:{type:'number'}, limit:{type:'number'}},
    output:{schema:{type:'json'},render:(_args:unknown,value:unknown)=>[{type:'text' as const,text:JSON.stringify(value)}]},
    async execute(args) { return await readPaperJobInput(resolveDataRoot(config), configEngine(config), args) as never },
  })), 'sr_read_job_input')
  ctx.effect(() => ctx.tools.register(defineTool({ name: 'sr_selected_chats',
    description: '读取用户在文献页明确选中的多个 chat 和总结问题，附原文证据、历史范围与截断说明。不自动扩大选择。',
    parameters: {}, output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => [{ type: 'text' as const, text: JSON.stringify(value) }] },
    async execute() {
      const engine = configEngine(config)
      const selection = await engine(['paper-chat'], { action: 'selection_get' })
      return await readSelectedChats(engine, createNativeRpc(ctx), selection) as never
    },
  })), 'sr_selected_chats')
  ctx.effect(() => ctx.tools.register(defineTool({ name: 'sr_paper_context',
    description: '读取本 chat 绑定论文的身份、摘要、已确认结论及当前 Figure。连续讨论前调用；聊天推测不是论文事实。',
    parameters: {}, output: { schema: { type: 'json' }, render: (_args: unknown, value: unknown) => [{ type: 'text' as const, text: JSON.stringify(value) }] },
    async execute(_args, exec) {
      const result = await engineJson(config, ['paper-chat'], { action: 'context_for_session', session_id: exec.agent?.session?.id })
      if (!result.ok || !result.json) throw new Error('paper_context_unavailable')
      return {...result.json,active_figure:figureLinks((result.json as any).active_figure,`http://127.0.0.1:${(ctx.webServer as any).port}`)} as never
    },
  })), 'sr_paper_context')
}
