// 使用独立 Profile、合成论文和本地模型适配器；不读取真实账号或论文。
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { buildAndPack, prepareEngine, materializeFixture, installPlugin, resolveDshRuntime,
  sanitizedDshEnvironment, startReaderWithRetry, stopOwned } from './acceptance-dsh.mjs'
import { nativeRpc } from '../lib/paper_sessions.js'

const root = await fs.mkdtemp(path.join(os.tmpdir(), 'sr-reading-chat-'))
const home = path.join(root, 'home'), dataRoot = path.join(root, 'library')
const output = path.resolve('outputs/v0.2/reading-assistant')
await fs.mkdir(output, {recursive:true}); await fs.mkdir(dataRoot, {recursive:true})
const evidence = {root, steps:[], checks:[], mode:'native-host-synthetic-model'}
const check = (name, value) => { assert.ok(value, name); evidence.checks.push(name); console.log('PASS: ' + name) }
let host, browser
try {
  const runtime = await resolveDshRuntime(), tarball = process.env.SR_ACCEPTANCE_TARBALL || await buildAndPack(root, evidence)
  const engine = await prepareEngine(dataRoot, evidence), nonce = String(Date.now())
  const fixture = await materializeFixture(dataRoot, nonce, evidence)
  await installPlugin(runtime, home, tarball, dataRoot, engine.python, evidence)
  await fs.appendFile(path.join(home, 'profiles', 'reader-review-acceptance', 'cordis.patch.yml'),
    `- insert:\n    - id: acceptance-local\n      name: ${JSON.stringify(pathToFileURL(path.resolve('scripts/fixtures/local-paper-model.mjs')).href)}\n      config:\n        dshEntry: ${JSON.stringify(runtime.source)}\n`)
  const env = {...sanitizedDshEnvironment(), DSH_HOME:home, PYTHONPATH:engine.pythonPath}
  for (const key of ['OPENAI_API_KEY','ANTHROPIC_API_KEY','DEEPSEEK_API_KEY','NODE_OPTIONS','SR_SCOPE_CONTEXT']) delete env[key]
  const running = await startReaderWithRetry({runtime,env,paperId:fixture.paperId,nonce,evidence}); host = running.host
  const url = `http://127.0.0.1:${running.port}`, readerUrl = `${url}/sr/reader/${encodeURIComponent(fixture.paperId)}`
  evidence.url = url; evidence.paperId = fixture.paperId
  const post = async (route, body) => {
    const response = await fetch(url + route, {method:'POST',headers:{'Content-Type':'application/json',Origin:url,'x-sr-csrf':'1'},body:JSON.stringify(body)})
    const value = await response.json(); if (!response.ok) throw new Error(value.error); return value
  }
  const policy = await (await fetch(url + '/sr/api/settings/models')).json()
  check('11 个步骤默认 medium，翻译 Luna、分析 Sol', Object.keys(policy.steps).length === 11 && Object.values(policy.steps).every(row => row.reasoningEffort === 'medium') && policy.steps.full_translation.model === 'gpt-5.6-luna')
  let updated = await post('/sr/api/settings/models', {revision:policy.revision, steps:{reader_chat:{provider:'acceptance-local',model:'gpt-5.6-luna',reasoningEffort:'high'}}})
  check('真实 API 保存自选模型与思考深度', updated.steps.reader_chat.model === 'gpt-5.6-luna' && updated.steps.reader_chat.reasoningEffort === 'high')
  await assert.rejects(post('/sr/api/settings/models', {revision:updated.revision,steps:{reader_chat:{provider:'acceptance-local',model:'gpt-5.6-luna',reasoningEffort:'max'}}}), /未提供/)
  check('未支持的思考档位在调用前拒绝', true)
  const generated = await post('/sr/api/models/run', {step:'radar_direction',input:'根据提供的合成材料提出一个研究方向。'})
  check('外部总管理员可调用所选步骤的实际模型', generated.text.includes('MODEL=gpt-5.6-sol EFFORT=medium'))
  const state = await post('/sr/api/chats/open', {paper_id:fixture.paperId})
  await nativeRpc(url,'session.prompt',{sessionId:state.session_id,mode:'queue',content:[{type:'text',text:'ACCEPTANCE_ROUTE_FULL_TRANSLATION'}]})
  let routed = false
  for (let attempt = 0; attempt < 70; attempt++) {
    const history = await nativeRpc(url,'session.history',{sessionId:state.session_id,maxMessages:50})
    routed = history.events.some(({event}) => event.type === 'assistant/message' && event.data.message.content.some(block => block.type === 'text' && block.text.includes('MODEL=gpt-5.6-luna EFFORT=medium')))
    if (routed) break
    await new Promise(resolve => setTimeout(resolve,500))
  }
  check('原生 Agent 在步骤工具之后实际使用 Luna medium', routed)
  const html = await (await fetch(readerUrl)).text()
  check('在线 Reader 注入悬浮对话', html.includes('data-reader-mode="online"') && html.includes('sr-reader-launcher'))
  const response = await fetch(readerUrl + '?download=1'), offline = await response.text()
  check('离线 HTML 为下载附件且禁止联网', response.headers.get('content-disposition')?.includes('attachment') && offline.includes('data-reader-mode="offline"') && offline.includes("connect-src 'none'"))
  const offlineFile = path.join(output,'离线阅读示例.html'); await fs.writeFile(offlineFile,offline)
  if (!process.env.SR_PLAYWRIGHT || !process.env.SR_BROWSER) throw new Error('SR_PLAYWRIGHT and SR_BROWSER are required for browser acceptance')
  const {chromium} = await import(pathToFileURL(process.env.SR_PLAYWRIGHT).href)
  browser = await chromium.launch({headless:true,executablePath:process.env.SR_BROWSER})
  const page = await browser.newPage({viewport:{width:1366,height:950}})
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await page.goto(readerUrl)
  const selection = await page.evaluate(() => {
    const source = [...document.querySelectorAll('.reading-block .source-primary')].find(node => node.getBoundingClientRect().height > 0 && node.innerText.trim().length > 40)
    const block = source.closest('.reading-block'); source.scrollIntoView({block:'center'})
    const range = document.createRange(); range.selectNodeContents(source); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range)
    document.dispatchEvent(new MouseEvent('mouseup'))
    return {block_ids:[block.dataset.block],quote:selection.toString().trim()}
  })
  check('浏览器选中了可见正文', selection.quote.length > 0)
  await page.keyboard.press('Alt+Shift+E')
  await page.getByText('可继续追问',{exact:true}).waitFor({timeout:40000})
  check('选区快捷键实际执行自选 Luna high', (await page.locator('.sr-reader-chat-message[data-role=assistant]').textContent()).includes('MODEL=gpt-5.6-luna EFFORT=high'))
  await page.getByRole('textbox',{name:'向阅读助手提问'}).fill('请接着解释一下。')
  await page.getByRole('button',{name:'发送',exact:true}).click()
  await page.getByText('可继续追问',{exact:true}).waitFor({timeout:40000})
  check('悬浮对话带上前一轮上下文', (await page.locator('.sr-reader-chat-message[data-role=assistant]').last().textContent()).includes('MESSAGES=3'))
  await page.screenshot({path:path.join(output,'在线阅读助手.png'),fullPage:false})
  const sha = await page.evaluate(() => document.body.dataset.sourcePdfSha256)
  await assert.rejects(post('/sr/api/reader/chat',{paper_id:fixture.paperId,source_pdf_sha256:'f'.repeat(64),question:'test',selection}), /reader_source_changed/)
  await assert.rejects(post('/sr/api/reader/chat',{paper_id:fixture.paperId,source_pdf_sha256:sha,question:'test',selection:{...selection,quote:'伪造原文'}}), /reader_selection_changed/)
  check('错误 PDF 身份和伪造选区均被拒绝', true)
  await page.setViewportSize({width:390,height:844})
  check('移动宽度在线对话无横向溢出', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.screenshot({path:path.join(output,'在线阅读助手-手机.png'),fullPage:false})
  const offlinePage = await browser.newPage({viewport:{width:390,height:844}})
  const remote = []; offlinePage.on('request', request => { if (/^https?:/.test(request.url())) remote.push(request.url()) })
  await offlinePage.goto(pathToFileURL(offlineFile).href)
  check('手机宽度离线文件可独立阅读且图片完整', await offlinePage.evaluate(() => document.documentElement.scrollWidth <= innerWidth && [...document.images].every(img => img.complete && img.naturalWidth > 0)))
  check('离线文件没有联网请求或聊天按钮', remote.length === 0 && await offlinePage.locator('.sr-reader-launcher').count() === 0)
  await offlinePage.screenshot({path:path.join(output,'离线阅读-手机.png'),fullPage:false})
  check('阅读页没有 JavaScript 错误', errors.length === 0)
  await page.setViewportSize({width:1440,height:1050})
  await page.goto(url + '/?sr-paper=' + encodeURIComponent(fixture.paperId))
  await page.getByText('设置与状态',{exact:true}).first().click({timeout:30000})
  const picker = page.getByLabel('摘要翻译模型', {exact:true})
  await picker.selectOption({label:'gpt-5.6-sol'})
  await page.getByLabel('摘要翻译思考深度',{exact:true}).selectOption('low')
  const row = page.locator('.sr-setting-row').filter({has:picker})
  await row.getByRole('button',{name:'保存',exact:true}).click()
  await row.getByText('已保存',{exact:true}).waitFor()
  const savedUi = await (await fetch(url + '/sr/api/settings/models')).json()
  check('设置页逐步骤下拉选择实际保存并保持其他步骤', savedUi.steps.abstract_translation.model === 'gpt-5.6-sol' && savedUi.steps.abstract_translation.reasoningEffort === 'low' && savedUi.steps.full_translation.model === 'gpt-5.6-luna')
  await picker.scrollIntoViewIfNeeded()
  await page.screenshot({path:path.join(output,'步骤模型设置.png'),fullPage:false})
  evidence.status = 'passed'
} catch (error) {
  evidence.status = 'failed'; evidence.error = error.stack
  if (browser) for (const [index, page] of browser.contexts().flatMap(context => context.pages()).entries()) {
    await fs.writeFile(path.join(output,`failure-${index}.txt`),await page.locator('body').innerText()).catch(()=>{})
    await page.screenshot({path:path.join(output,`failure-${index}.png`)}).catch(()=>{})
  }
  throw error
}
finally {
  await browser?.close(); if (host) await stopOwned(host)
  await fs.writeFile(path.join(output,'验收.json'),JSON.stringify(evidence,null,2))
}
