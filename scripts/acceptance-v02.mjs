import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { buildAndPack, prepareEngine, materializeFixture, installPlugin, resolveDshRuntime,
  sanitizedDshEnvironment, startReaderWithRetry, stopOwned } from './acceptance-dsh.mjs'

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-reader-acceptance-v02-'))
const home = path.join(root, 'home'), dataRoot = path.join(root, 'library')
await fs.mkdir(dataRoot, { recursive: true })
const evidence = { root, steps: [], checks: [], mode: 'native-dsh-synthetic-model', startedAt: new Date().toISOString() }
const report = path.resolve('outputs/v0.2/native-chat.json')
const check = (name, value) => { assert.ok(value, name); evidence.checks.push({ name, passed: true }) }
let host, running, env
try {
  const runtime = await resolveDshRuntime()
  const tarball = await buildAndPack(root, evidence)
  const engine = await prepareEngine(dataRoot, evidence)
  const nonce = String(Date.now())
  const fixture = await materializeFixture(dataRoot, nonce, evidence)
  const figureProcess = await promisify(execFile)('node', ['scripts/run-python.mjs', 'scripts/figure_acceptance_fixture.py', dataRoot], {encoding:'utf8'})
  const figureFixture = JSON.parse(figureProcess.stdout.trim().split(/\r?\n/).at(-1))
  await installPlugin(runtime, home, tarball, dataRoot, engine.python, evidence)
  const profile = path.join(home, 'profiles', 'reader-review-acceptance', 'cordis.patch.yml')
  await fs.appendFile(profile, `- insert:\n    - id: acceptance-local\n      name: ${JSON.stringify(pathToFileURL(path.resolve('scripts/fixtures/local-paper-model.mjs')).href)}\n      config:\n        dshEntry: ${JSON.stringify(runtime.source)}\n`)
  env = { ...sanitizedDshEnvironment(), DSH_HOME: home, PYTHONPATH: engine.pythonPath }
  for (const key of ['OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY', 'NODE_OPTIONS', 'SR_SCOPE_CONTEXT']) delete env[key]
  const start = async () => {
    running = await startReaderWithRetry({ runtime, env, paperId: fixture.paperId, nonce, evidence })
    host = running.host
    return `http://127.0.0.1:${running.port}`
  }
  let url = await start()
  const { nativeRpc, readSelectedChats } = await import('../lib/paper_sessions.js')
  const { engineJson } = await import('../lib/cli.js')
  const config = { dataRoot, enginePython: engine.python }
  const invokeEngine = async (args, input) => {
    const result = await engineJson(config, args, input, { PYTHONPATH: engine.pythonPath })
    if (!result.ok) throw new Error(result.json?.error || result.stderr || 'engine_failed')
    return result.json
  }
  const post = async (route, body) => {
    const response = await fetch(url + route, { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: url, 'x-sr-csrf': '1' }, body: JSON.stringify(body) })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || 'http_failed')
    return result
  }
  const paper = fixture.paperId
  const first = await post('/sr/api/chats/open', { paper_id: paper })
  check('原生 chat 重复打开复用同一 sessionId', first.session_id === (await post('/sr/api/chats/open', { paper_id: paper })).session_id)
  const secondPaper = await invokeEngine(['library-ingest'], { title: '独立第二篇合成论文', authors: [] })
  const reserved = await invokeEngine(['paper-chat'], { action: 'ensure', paper_id: secondPaper.paper_id })
  const priorWorkspace = await nativeRpc(url, 'workspace.create', { path: home })
  await nativeRpc(url, 'session.create', { sessionId: reserved.session_id, workspaceId: priorWorkspace.workspace.workspaceId, agentPreset: 'scientific-reading' })
  const second = await post('/sr/api/chats/open', { paper_id: secondPaper.paper_id })
  check('打开已有 chat 保留它的原生工作区', second.session_id === reserved.session_id)
  check('两篇论文分配不同原生 chat', first.session_id !== second.session_id)
  const workspaces = await nativeRpc(url, 'workspace.list', {})
  check('新 chat 在发送首条消息前已加入原生工作区', JSON.stringify(workspaces).includes(second.session_id))
  await nativeRpc(url, 'session.selectModel', { sessionId: first.session_id, provider: 'acceptance-local', model: 'scope-smoke' })
  const round = async count => {
    await nativeRpc(url, 'session.prompt', { sessionId: first.session_id, mode: 'queue', content: [{ type: 'text', text: '读取本篇文献上下文；这是合成验收第 ' + count + ' 轮。' }] })
    for (let attempt = 0; attempt < 80; attempt++) {
      const history = await nativeRpc(url, 'session.history', { sessionId: first.session_id, maxMessages: 100 })
      const completions = history.events.filter(({ event }) => event.type === 'assistant/message' &&
        event.data.message.content.some(block => block.type === 'text' && block.text.includes('ACCEPTANCE_LOCAL_TOOL_LOOP_OK'))).length
      if (completions >= count) return history
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    throw new Error('native_chat_tool_loop_failed')
  }
  await round(1)
  check('真实 DSH 模型循环读取当前论文并接收工具结果', true)
  await stopOwned(host); host = null
  url = await start()
  check('重启后恢复同一 chat', (await post('/sr/api/chats/open', { paper_id: paper })).session_id === first.session_id)
  const folder = await invokeEngine(['folder-create', '--name', 'chat 移动验收'])
  await invokeEngine(['classification-apply', '--input', '-'], { proposals: [{ paper_id: paper, folder_name: folder.name, confidence: 1, tags: [] }] })
  await round(2)
  check('移动分类并重启后继续原 chat 的第二轮工具对话', true)
  await post('/sr/api/chats/select', { question: '比较所选合成论文', selection: [{ paper_id: paper }] })
  const selected = await invokeEngine(['paper-chat'], { action: 'selection_get' })
  const reads = []
  const summary = await readSelectedChats(invokeEngine, (method, payload) => { reads.push(payload.sessionId); return nativeRpc(url, method, payload) }, selected)
  check('多选读取不混入未选会话且保留论文与工具证据', reads.length === 1 && reads[0] === first.session_id &&
    summary.chats[0].history.text.includes(paper) && !summary.chats[0].history.text.includes(secondPaper.paper_id))
  const figureChat = await post('/sr/api/chats/open', {paper_id:figureFixture.paper_id})
  await nativeRpc(url, 'session.selectModel', {sessionId:figureChat.session_id, provider:'acceptance-local', model:'scope-smoke'})
  const waitFigure = async marker => {
    for (let attempt=0; attempt<80; attempt++) {
      const history = await nativeRpc(url, 'session.history', {sessionId:figureChat.session_id, maxMessages:100})
      if (history.events.some(({event}) => event.type==='assistant/message' && event.data.message.content.some(part=>part.type==='text' && part.text.includes(marker)))) return
      await new Promise(resolve=>setTimeout(resolve,500))
    }
    throw new Error('figure_model_receipt_missing')
  }
  const selectedFigure = await post('/sr/api/chats/figure', figureFixture)
  await waitFigure('IMAGE_BYTES_SHA256=' + selectedFigure.context.image_sha256)
  check('原生模型适配器确实读取并核对了图片字节 SHA', true)
  const nextFigure = await post('/sr/api/chats/figure', {...figureFixture, asset_id:'mineru-p0002-img0001', text_only:true})
  await waitFigure('TEXT_ONLY_VERIFIED ASSET=mineru-p0002-img0001')
  check('换图沿用原 chat 且仅文字模式没有传入图像', selectedFigure.session_id===nextFigure.session_id && nextFigure.context.revision===2)
  const figureHtml = await (await fetch(url + '/sr/reader/' + figureFixture.paper_id)).text()
  check('打包 Reader 包含当前 PDF 指纹与讨论按钮', figureHtml.includes(figureFixture.source_pdf_sha256) && figureHtml.includes('figure-discuss-trigger'))
  evidence.figure = {fixture:figureFixture, sessionId:figureChat.session_id, current:nextFigure.context}
  evidence.passed = true
  evidence.url = url
  evidence.paperId = paper
  evidence.sessionId = first.session_id
  evidence.summary = summary
  await fs.mkdir(path.dirname(report), { recursive: true })
  await fs.writeFile(report, JSON.stringify(evidence, null, 2))
  console.log(JSON.stringify({ passed: true, url, root, report, paperId: paper, sessionId: first.session_id }))
  if (process.argv.includes('--hold')) {
    while (true) {
      try { await fs.access(path.join(root, 'stop')); break } catch {}
      await new Promise(resolve => setTimeout(resolve, 1000))
    }
  }
} catch (error) {
  evidence.passed = false; evidence.error = error.stack
  if (host) evidence.hostOutput = { stdout: Buffer.concat(host.output.stdout).toString(), stderr: Buffer.concat(host.output.stderr).toString() }
  process.exitCode = 1
  console.error(error.stack)
} finally {
  if (host) await stopOwned(host)
  await fs.mkdir(path.dirname(report), { recursive: true })
  await fs.writeFile(report, JSON.stringify(evidence, null, 2))
}
