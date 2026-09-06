import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import readline from 'node:readline'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const serverScript = path.join(repositoryRoot, 'scripts', 'reader-review-server.mjs')


async function request(port, pathname, method = 'GET') {
  return await new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port, path: pathname, method },
      (response) => {
        const chunks = []
        response.on('data', (chunk) => chunks.push(chunk))
        response.on('end', () => resolve({
          status: response.statusCode,
          headers: response.headers,
          body: Buffer.concat(chunks).toString('utf8'),
        }))
      },
    )
    req.on('error', reject)
    req.end()
  })
}


async function waitForLine(stream, timeoutMs = 5000) {
  const lines = readline.createInterface({ input: stream })
  let timer
  try {
    return await Promise.race([
      new Promise((resolve) => lines.once('line', resolve)),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('server handshake timeout')), timeoutMs)
      }),
    ])
  } finally {
    clearTimeout(timer)
    lines.close()
  }
}


async function waitForExit(child, timeoutMs = 5000) {
  if (child.exitCode !== null) return child.exitCode
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('server exit timeout')),
      timeoutMs,
    )
    child.once('exit', (code) => {
      clearTimeout(timer)
      resolve(code)
    })
  })
}


async function createReviewRoot(base) {
  const reviewRoot = path.join(base, 'review-root')
  const fakeRepository = path.join(base, 'repository')
  await fs.mkdir(path.join(fakeRepository, 'review'), { recursive: true })
  await fs.writeFile(
    path.join(fakeRepository, 'review', 'index.html'),
    '<!doctype html><title>Reader review</title>',
    'utf8',
  )
  for (const version of ['baseline', 'candidate']) {
    const folder = path.join(reviewRoot, version, 'formula-outline')
    await fs.mkdir(folder, { recursive: true })
    await fs.writeFile(
      path.join(folder, 'reader.html'),
      `<!doctype html><title>${version}</title>`,
      'utf8',
    )
  }
  await fs.writeFile(
    path.join(reviewRoot, 'session.json'),
    JSON.stringify({
      contract_version: 'reader-review-session-v1',
      session_id: '1'.repeat(32),
      cases: { 'formula-outline': { kind: 'fixture' } },
    }),
    'utf8',
  )
  await fs.writeFile(
    path.join(reviewRoot, 'review-manifest.json'),
    JSON.stringify({
      contract_version: 'reader-review-manifest-v1',
      revision: 1,
      cases: {
        'formula-outline': {
          baseline_url: '/content/baseline/formula-outline/reader.html',
          candidate_url: '/content/candidate/formula-outline/reader.html?revision=1',
        },
      },
    }),
    'utf8',
  )
  return { reviewRoot, fakeRepository }
}


function startServer({ reviewRoot, fakeRepository, port = 0, token = '2'.repeat(32) }) {
  return spawn(
    process.execPath,
    [
      serverScript,
      '--review-root', reviewRoot,
      '--repository-root', fakeRepository,
      '--port', String(port),
      '--session-id', '1'.repeat(32),
      '--token', token,
    ],
    {
      cwd: repositoryRoot,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
      shell: false,
    },
  )
}


async function stopServer(child) {
  if (child.exitCode === null) child.kill('SIGTERM')
  await waitForExit(child)
}


const base = await fs.mkdtemp(path.join(os.tmpdir(), 'reader-review-server-test-'))
try {
  const { reviewRoot, fakeRepository } = await createReviewRoot(base)
  const child = startServer({ reviewRoot, fakeRepository })
  const stderr = []
  child.stderr.on('data', (chunk) => stderr.push(chunk))
  const handshake = JSON.parse(await waitForLine(child.stdout))
  const port = handshake.port

  try {
    assert.equal(handshake.contract_version, 'reader-review-server-v1')
    assert.equal(handshake.pid, child.pid)
    assert.equal(handshake.repository_root, path.resolve(fakeRepository))
    assert.equal(handshake.session_id, '1'.repeat(32))
    assert.equal(handshake.token, '2'.repeat(32))

    const metadata = JSON.parse(
      await fs.readFile(path.join(reviewRoot, 'server.json'), 'utf8'),
    )
    assert.deepEqual(metadata, handshake)

    assert.equal((await request(port, '/health')).status, 200)
    assert.equal((await request(port, '/review')).status, 200)
    assert.equal((await request(port, '/review/index.html')).status, 200)
    assert.equal((await request(port, '/api/review-manifest')).status, 200)
    assert.equal(
      (await request(port, '/content/baseline/formula-outline/reader.html')).status,
      200,
    )
    assert.equal(
      (await request(port, '/content/candidate/formula-outline/reader.html')).status,
      200,
    )
    assert.equal((await request(port, '/../session.json')).status, 404)
    assert.equal(
      (await request(port, '/content/candidate/%2e%2e/session.json')).status,
      404,
    )
    assert.equal((await request(port, '/unknown.txt')).status, 404)
    assert.equal((await request(port, '/review', 'POST')).status, 405)

    const candidate = path.join(reviewRoot, 'candidate', 'formula-outline', 'reader.html')
    const outside = path.join(base, 'outside.html')
    await fs.writeFile(outside, '<!doctype html><title>outside</title>', 'utf8')
    await fs.rm(candidate)
    let symlinkCreated = true
    try {
      await fs.symlink(outside, candidate, 'file')
    } catch (error) {
      if (error?.code === 'EPERM') symlinkCreated = false
      else throw error
    }
    if (symlinkCreated) {
      assert.equal(
        (await request(port, '/content/candidate/formula-outline/reader.html')).status,
        404,
      )
    }
  } finally {
    await stopServer(child)
  }
  assert.equal(stderr.length, 0, Buffer.concat(stderr).toString('utf8'))
  const serverFile = path.join(reviewRoot, 'server.json')
  if (process.platform === 'win32') {
    const stale = JSON.parse(await fs.readFile(serverFile, 'utf8'))
    assert.equal(stale.pid, child.pid)
    assert.equal(stale.token, '2'.repeat(32))
    await fs.rm(serverFile)
  } else {
    await assert.rejects(fs.stat(serverFile), /ENOENT/)
  }

  const sentinel = http.createServer((_request, response) => response.end('sentinel'))
  await new Promise((resolve) => sentinel.listen(0, '127.0.0.1', resolve))
  const sentinelPort = sentinel.address().port
  try {
    const conflict = startServer({ reviewRoot, fakeRepository, port: sentinelPort })
    const conflictStderr = []
    conflict.stderr.on('data', (chunk) => conflictStderr.push(chunk))
    const code = await waitForExit(conflict)
    assert.notEqual(code, 0)
    assert.match(Buffer.concat(conflictStderr).toString('utf8'), /review_port_in_use/)
    const response = await request(sentinelPort, '/health')
    assert.equal(response.status, 200)
    assert.equal(response.body, 'sentinel')
  } finally {
    await new Promise((resolve) => sentinel.close(resolve))
  }

  console.log('PASS: Reader 审核服务器路由、安全与端口所有权合同通过')
} finally {
  await fs.rm(base, { recursive: true, force: true })
}
