import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('..', import.meta.url))
const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'))
const verifier = join(root, 'scripts', 'verify_navigation_runtime.mjs')
assert.equal(existsSync(verifier), true, '缺少导航运行验收脚本')
const source = readFileSync(verifier, 'utf8')
for (const marker of ['npm_pack_dry_run', 'npm_pack', '60', 'port_not_released', 'worker_process_leaked', 'windowsHide: true']) {
  assert.match(source, new RegExp(marker), `导航验收缺少门禁：${marker}`)
}
assert.equal(manifest.scripts?.['test:navigation-runtime'], 'node tests/navigation-runtime.mjs')
assert.equal(manifest.scripts?.['verify:navigation-runtime'], 'node scripts/verify_navigation_runtime.mjs')

const fixture = mkdtempSync(join(tmpdir(), 'sr-navigation-fixture-'))
const fakeDsh = join(fixture, 'fake-dsh.mjs')
const capture = join(fixture, 'capture.json')
writeFileSync(capture, '{}', 'utf8')
writeFileSync(fakeDsh, `
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { createServer } from 'node:http'
const args=process.argv.slice(2), capture=process.env.FAKE_DSH_CAPTURE
const save=(extra)=>{let old={};try{old=JSON.parse(readFileSync(capture,'utf8'))}catch{};writeFileSync(capture,JSON.stringify({...old,...extra}))}
if(args.length===1&&args[0]==='--version'){console.log('0.1.0-rc.7');process.exit(0)}
if(args[0]==='plugin'){save({installed:existsSync(args[4]),secretAtInstall:Boolean(process.env.FEISHU_APP_ID||process.env.FEISHU_APP_SECRET),dshHome:process.env.DSH_HOME,userProfile:process.env.USERPROFILE});process.exit(0)}
if(args.includes('--profile')){
 if(process.env.FAKE_DSH_MODE==='failure')process.exit(23)
 const papers=[]; let requests=[]
 const server=createServer(async(req,res)=>{let body='';for await(const c of req)body+=c;requests.push(req.method+' '+req.url);save({requests,secretAtStart:Boolean(process.env.FEISHU_APP_ID||process.env.FEISHU_APP_SECRET)})
  const url=new URL(req.url,'http://local'); const send=(status,value,type='application/json')=>{res.writeHead(status,{'Content-Type':type});res.end(type==='application/json'?JSON.stringify(value):value)}
  if(req.method==='POST'&&url.pathname==='/sr/api/library'){const m=JSON.parse(body);const id='title_runtime_'+String(papers.length+1).padStart(2,'0');papers.push({paper_id:id,title:m.title,authors_short:'Engineer',year:2026,folder:null,tags:[],abstract_status:'ready',full_read_status:'completed',feishu_sync_state:'disabled',has_pdf:true,has_reader:true});return send(200,{paper_id:id})}
  if(req.method==='GET'&&url.pathname==='/sr/api/library'){let rows=papers;if(url.searchParams.get('q'))rows=rows.filter(p=>p.title.includes(url.searchParams.get('q')));if(url.searchParams.get('folder')==='__unclassified__')rows=rows.filter(p=>p.folder===null);const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||50);return send(200,{items:rows.slice((page-1)*size,page*size),total:rows.length,page,page_size:size,folders:[{folder_id:'folder_bridge',name:'Bridge'}]})}
  if(req.method==='GET'&&url.pathname==='/sr/api/folders')return send(200,[{folder_id:'folder_bridge',name:'Bridge'}])
  if(req.method==='POST'&&url.pathname==='/sr/api/batch')return send(200,{batch_id:'batch_0000000000000001',status:'queued',total:JSON.parse(body).selection.length})
  const parts=url.pathname.split('/').filter(Boolean);if(parts[0]==='sr'&&parts[1]==='api'&&parts[2]==='paper'&&parts[3]?.startsWith('title_runtime_')){const id=parts[3],action=parts[4];if(action==='abstract')return send(200,{paper_id:id,status:'ready',abstract_en:'Engineering abstract',abstract_zh:'工程摘要'});if(action==='pdf')return send(200,'%PDF fixture','application/pdf');if(action==='assets')return send(200,{figures:2,tables:1,exports_path:'fixture'});return send(200,{paper_id:id,item:papers.find(p=>p.paper_id===id)})}
  if(url.pathname==='/sr/reader/title_runtime_01')return send(200,'<html>fixture reader</html>','text/html')
  send(404,{error:'not_found'})
 });server.listen(0,'127.0.0.1',()=>console.log('dsh web: http://127.0.0.1:'+server.address().port));const stop=()=>server.close(()=>{save({stopped:true});process.exit(0)});process.on('SIGTERM',stop);process.on('SIGINT',stop);await new Promise(()=>{})
}
process.exit(9)
`, 'utf8')

try {
  const result = spawnSync(process.execPath, [verifier, '--dsh-bin', fakeDsh], {
    cwd: root, encoding: 'utf8', timeout: 120_000, windowsHide: true,
    env: { ...process.env, FAKE_DSH_CAPTURE: capture, FEISHU_APP_ID: 'must-not-leak', FEISHU_APP_SECRET: 'must-not-leak', npm_execpath: '' },
  })
  assert.equal(result.status, 0, result.stderr)
  const output = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1))
  assert.equal(output.status, 'navigation_runtime_verified')
  assert.equal(output.imported, 60)
  assert.equal(existsSync(output.temporary), false, '验收结束必须删除临时目录')
  const captured = JSON.parse(readFileSync(capture, 'utf8'))
  assert.equal(captured.installed, true)
  assert.equal(captured.secretAtInstall, false)
  assert.equal(captured.secretAtStart, false)
  assert.ok(captured.requests.some((request) => request === 'GET /sr/api/paper/title_runtime_01/assets'))
  assert.equal(existsSync(captured.dshHome), false)
  assert.equal(existsSync(captured.userProfile), false)

  writeFileSync(capture, '{}', 'utf8')
  const failure = spawnSync(process.execPath, [verifier, '--dsh-bin', fakeDsh], {
    cwd: root, encoding: 'utf8', timeout: 120_000, windowsHide: true,
    env: { ...process.env, FAKE_DSH_MODE: 'failure', FAKE_DSH_CAPTURE: capture, FEISHU_APP_ID: 'must-not-leak', FEISHU_APP_SECRET: 'must-not-leak', npm_execpath: '' },
  })
  assert.notEqual(failure.status, 0)
  const failedCapture = JSON.parse(readFileSync(capture, 'utf8'))
  assert.equal(existsSync(failedCapture.dshHome), false, '启动失败也必须删除临时 DSH_HOME')
  assert.equal(existsSync(failedCapture.userProfile), false, '启动失败也必须删除临时 USERPROFILE')
  console.log('PASS: 60篇导航真实tarball与HTTP隔离运行验收')
} finally { rmSync(fixture, { recursive: true, force: true }) }
