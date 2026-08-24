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
for (const marker of ['npm_pack_dry_run', 'npm_pack', '60', 'port_not_released', 'worker_process_leaked', 'windowsHide: true', '--engine-python', '--dump-config', 'client.js', 'library.sqlite', 'status.json', 'launch.json', 'process_start_identity']) {
  assert.match(source, new RegExp(marker), `导航验收缺少门禁：${marker}`)
}
assert.doesNotMatch(source, /SR_DATA_ROOT|SR_EXTERNAL_PROVIDER|scientific-reading-navigation-test/, '导航验收不得依赖宿主未消费的假配置')
assert.match(source, /join\(userProfile, 'scientific-reading-data'\)/, 'dataRoot 必须等于临时 USERPROFILE 下的正式默认目录')
assert.match(source, /engine_import_probe/, '必须真实探测 scientific_reading import')
assert.match(source, /batch_children_readback_failed/, '批处理必须回读父任务与子项')
assert.equal(manifest.scripts?.['test:navigation-runtime'], 'node tests/navigation-runtime.mjs')
assert.equal(manifest.scripts?.['verify:navigation-runtime'], 'node scripts/verify_navigation_runtime.mjs')

const fixture = mkdtempSync(join(tmpdir(), 'sr-navigation-fixture-'))
const fakeDsh = join(fixture, 'fake-dsh.mjs')
const capture = join(fixture, 'capture.json')
writeFileSync(capture, '{}', 'utf8')
writeFileSync(fakeDsh, `
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { createServer } from 'node:http'
import { spawn, spawnSync } from 'node:child_process'
const args=process.argv.slice(2), capture=process.env.FAKE_DSH_CAPTURE
const save=(extra)=>{let old={};try{old=JSON.parse(readFileSync(capture,'utf8'))}catch{};writeFileSync(capture,JSON.stringify({...old,...extra}))}
const identity=(pid)=>{
 if(process.platform==='win32'){
  const command="$p=Get-Process -Id "+pid+" -ErrorAction Stop; 'windows:{0:x16}' -f $p.StartTime.ToUniversalTime().ToFileTimeUtc()"
  const result=spawnSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',command],{encoding:'utf8',windowsHide:true})
  return result.status===0?result.stdout.trim():null
 }
 if(process.platform==='linux'){
  const stat=readFileSync('/proc/'+pid+'/stat','ascii');return 'linux:'+stat.slice(stat.lastIndexOf(')')+2).split(/\\s+/)[19]
 }
 return null
}
if(args.length===1&&args[0]==='--version'){console.log('0.1.0-rc.7');process.exit(0)}
if(args[0]==='plugin'){
 save({installed:existsSync(args[4]),installProfile:args[2],secretAtInstall:Boolean(process.env.FEISHU_APP_ID||process.env.FEISHU_APP_SECRET),dshHome:process.env.DSH_HOME,userProfile:process.env.USERPROFILE,enginePython:process.env.SCIENTIFIC_READING_PYTHON})
 process.exit(args[2]==='web'?0:10)
}
if(args.length===3&&args[0]==='--profile'&&args[1]==='web'&&args[2]==='--dump-config'){
 save({dumped:true});console.log("plugins:\\n  - id: scientific-reading\\n    name: '@dsh-external/dsh-scientific-reading'");process.exit(0)
}
if(args.includes('--profile')){
 if(args[args.indexOf('--profile')+1]!=='web')process.exit(11)
 if(process.env.FAKE_DSH_MODE==='failure')process.exit(23)
 const papers=Array.from({length:60},(_,offset)=>{const index=offset+1;return {paper_id:'title_runtime_'+String(index).padStart(2,'0'),title:index===37?'Rare Composite Bridge Search Target':'Modular Bridge Load Study '+String(index).padStart(2,'0'),authors_short:'Runtime Engineer',year:2026,folder:index===37?'Bridge':null,tags:index===37?['bridge']:[],abstract_status:'ready',full_read_status:index===37?'精读完成':'待精读',feishu_sync_state:'disabled',has_pdf:index===37,has_reader:index===37}})
 const dataRoot=join(process.env.USERPROFILE,'scientific-reading-data'), jobs=join(dataRoot,'jobs'), jobRoot=join(jobs,'job_bbbbbbbbbbbbbbbb')
 mkdirSync(jobRoot,{recursive:true})
 const worker=spawn(process.execPath,['-e','setTimeout(()=>process.exit(0),15000);setInterval(()=>{},1000)'],{detached:true,stdio:'ignore',windowsHide:true});worker.unref()
 const workerIdentity=identity(worker.pid)
 writeFileSync(join(jobRoot,'status.json'),JSON.stringify({state:'completed'}))
 writeFileSync(join(jobRoot,'launch.json'),JSON.stringify({pid:worker.pid,process_start_identity:workerIdentity}))
 save({workerPid:worker.pid,workerIdentity,dataRoot,workerStarted:true})
 let requests=[]
 const server=createServer(async(req,res)=>{let body='';for await(const c of req)body+=c;requests.push(req.method+' '+req.url);save({requests,secretAtStart:Boolean(process.env.FEISHU_APP_ID||process.env.FEISHU_APP_SECRET)})
  const url=new URL(req.url,'http://local');const send=(status,value,type='application/json')=>{res.writeHead(status,{'Content-Type':type});res.end(type==='application/json'?JSON.stringify(value):value)}
  if(req.method==='GET'&&url.pathname==='/plugins/@dsh-external/dsh-scientific-reading/client.js')return send(200,'window.__ModuleLoader__.load({})','text/javascript')
  if(req.method==='GET'&&url.pathname==='/sr/api/library'){
   let rows=papers
   if(url.searchParams.get('q'))rows=rows.filter(p=>p.title.includes(url.searchParams.get('q')))
   const folder=url.searchParams.get('folder')
   if(folder==='__unclassified__')rows=rows.filter(p=>p.folder===null)
   if(folder==='folder_bridge')rows=rows.filter(p=>p.folder==='Bridge')
   const page=Number(url.searchParams.get('page')||1),size=Number(url.searchParams.get('page_size')||50)
   return send(200,{items:rows.slice((page-1)*size,page*size),total:rows.length,page,page_size:size,jobs:{running:1,queued:0}})
  }
  if(req.method==='GET'&&url.pathname==='/sr/api/folders')return send(200,[{folder_id:'folder_bridge',name:'Bridge'}])
  if(req.method==='POST'&&url.pathname==='/sr/api/batch'){
   const input=JSON.parse(body), parent='job_aaaaaaaaaaaaaaaa', result={parent_job_id:parent,status:'completed',selection:input.selection,children:input.selection.map(paper_id=>({paper_id,status:'created'})),operation_id:'batch_fake',summary:{total:input.selection.length,created:input.selection.length,reused:0,needs_user:0,failed:0,pending:0}}
   const batches=join(jobs,'batches');mkdirSync(batches,{recursive:true});writeFileSync(join(batches,parent+'.json'),JSON.stringify(result));return send(200,result)
  }
  const parts=url.pathname.split('/').filter(Boolean)
  if(parts[0]==='sr'&&parts[1]==='api'&&parts[2]==='paper'&&parts[3]==='title_runtime_37'){
   const action=parts[4]
   if(action==='abstract')return send(200,{paper_id:parts[3],status:'ready',abstract_en:'First offline paragraph.',abstract_zh:'第一段离线摘要。'})
   if(action==='pdf')return send(200,Buffer.from('%PDF-1.4 fake'),'application/pdf')
   if(action==='assets'&&parts.length===5)return send(200,{contract:'asset-export-v1',figures:2,tables:1,exports_path:join(dataRoot,'papers',parts[3],'generations','fixture','exports')})
   if(action==='assets'&&parts.slice(5).join('/')==='figures/Fig_01.png')return send(200,Buffer.from([137,80,78,71,13,10,26,10]),'image/png')
   if(action==='assets'&&parts.slice(5).join('/')==='tables/Table_01.csv')return send(200,'metric,value\\nfixture,1\\n','text/csv')
   return send(200,{paper_id:parts[3],item:papers[36]})
  }
  if(url.pathname==='/sr/reader/title_runtime_37')return send(200,'<html>navigation fixture reader</html>','text/html')
  send(404,{error:'not_found'})
 })
 server.listen(0,'127.0.0.1',()=>console.log('dsh web: http://127.0.0.1:'+server.address().port))
 const stop=()=>server.close(()=>{save({stopped:true});process.exit(0)});process.on('SIGTERM',stop);process.on('SIGINT',stop);await new Promise(()=>{})
}
process.exit(9)
`, 'utf8')

try {
  const commonEnv = { ...process.env, SR_NAVIGATION_RUNTIME_FAKE_ENGINE: '1', FAKE_DSH_CAPTURE: capture, FEISHU_APP_ID: 'must-not-leak', FEISHU_APP_SECRET: 'must-not-leak', npm_execpath: '' }
  const result = spawnSync(process.execPath, [verifier, '--dsh-bin', fakeDsh, '--engine-python', process.execPath], {
    cwd: root, encoding: 'utf8', timeout: 120_000, windowsHide: true, env: commonEnv,
  })
  assert.equal(result.status, 0, result.stderr)
  const output = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1))
  assert.equal(output.status, 'navigation_runtime_verified')
  assert.equal(output.profile, 'web')
  assert.equal(output.imported, 60)
  assert.equal(existsSync(output.temporary), false, '验收结束必须删除临时目录')
  const captured = JSON.parse(readFileSync(capture, 'utf8'))
  assert.equal(captured.installed, true)
  assert.equal(captured.installProfile, 'web')
  assert.equal(captured.dumped, true)
  assert.equal(captured.enginePython, process.execPath)
  assert.equal(captured.secretAtInstall, false)
  assert.equal(captured.secretAtStart, false)
  assert.equal(captured.workerStarted, true, '假宿主必须启动可检测的子进程')
  assert.ok(captured.workerIdentity, '假 worker 必须记录进程启动身份')
  assert.ok(captured.requests.includes('GET /plugins/@dsh-external/dsh-scientific-reading/client.js'))
  assert.ok(captured.requests.includes('POST /sr/api/batch'))
  assert.equal(captured.requests.some((request) => request === 'POST /sr/api/library'), false, '不得通过 HTTP 入库触发派生任务')
  assert.equal(existsSync(captured.dshHome), false)
  assert.equal(existsSync(captured.userProfile), false)
  assert.throws(() => process.kill(captured.workerPid, 0), '验收结束必须清理临时 worker')

  writeFileSync(capture, '{}', 'utf8')
  const failure = spawnSync(process.execPath, [verifier, '--dsh-bin', fakeDsh, '--engine-python', process.execPath], {
    cwd: root, encoding: 'utf8', timeout: 120_000, windowsHide: true,
    env: { ...commonEnv, FAKE_DSH_MODE: 'failure' },
  })
  assert.notEqual(failure.status, 0)
  const failedCapture = JSON.parse(readFileSync(capture, 'utf8'))
  assert.equal(existsSync(failedCapture.dshHome), false, '启动失败也必须删除临时 DSH_HOME')
  assert.equal(existsSync(failedCapture.userProfile), false, '启动失败也必须删除临时 USERPROFILE')
  console.log('PASS: 60篇导航真实tarball、离线夹具与HTTP隔离运行验收')
} finally { rmSync(fixture, { recursive: true, force: true }) }
