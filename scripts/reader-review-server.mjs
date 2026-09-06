import crypto from 'node:crypto'
import fs from 'node:fs/promises'
import http from 'node:http'
import path from 'node:path'
import process from 'node:process'


const SERVER_CONTRACT = 'reader-review-server-v1'
const HOST = '127.0.0.1'
const CASE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/


function parseArgs(argv) {
  const values = {}
  for (let index = 0; index < argv.length; index += 2) {
    const name = argv[index]
    const value = argv[index + 1]
    if (!name?.startsWith('--') || value === undefined) {
      throw new Error('review_server_arguments_invalid')
    }
    values[name.slice(2)] = value
  }
  const port = Number(values.port ?? '8895')
  if (
    !values['review-root']
    || !values['repository-root']
    || !/^[0-9a-f]{32}$/.test(values['session-id'] ?? '')
    || !/^[0-9a-f]{32,128}$/.test(values.token ?? '')
    || !Number.isInteger(port)
    || port < 0
    || port > 65535
  ) {
    throw new Error('review_server_arguments_invalid')
  }
  return {
    reviewRoot: path.resolve(values['review-root']),
    repositoryRoot: path.resolve(values['repository-root']),
    sessionId: values['session-id'],
    token: values.token,
    port,
  }
}


function isContained(root, candidate) {
  const relative = path.relative(root, candidate)
  return relative === '' || (
    relative !== '..'
    && !relative.startsWith(`..${path.sep}`)
    && !path.isAbsolute(relative)
  )
}


async function atomicWriteJson(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true })
  const temporary = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${crypto.randomBytes(8).toString('hex')}.tmp`,
  )
  const handle = await fs.open(temporary, 'wx')
  try {
    await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, 'utf8')
    await handle.sync()
  } finally {
    await handle.close()
  }
  try {
    await fs.rename(temporary, file)
  } finally {
    await fs.rm(temporary, { force: true })
  }
}


async function readJson(file) {
  const value = JSON.parse(await fs.readFile(file, 'utf8'))
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('review_manifest_invalid')
  }
  return value
}


async function safeFile(reviewRoot, candidate) {
  const root = await fs.realpath(reviewRoot)
  const stat = await fs.lstat(candidate)
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('not_found')
  const resolved = await fs.realpath(candidate)
  if (!isContained(root, resolved)) throw new Error('not_found')
  return resolved
}


function send(response, status, body, contentType) {
  const payload = Buffer.isBuffer(body) ? body : Buffer.from(String(body), 'utf8')
  response.writeHead(status, {
    'Content-Type': contentType,
    'Content-Length': payload.byteLength,
    'X-Content-Type-Options': 'nosniff',
    'Cache-Control': 'no-store',
  })
  response.end(payload)
}


function notFound(response) {
  send(response, 404, 'Not Found\n', 'text/plain; charset=utf-8')
}


async function contentFile(reviewRoot, pathname) {
  const match = /^\/content\/(baseline|candidate)\/([^/]+)\/reader\.html$/.exec(pathname)
  if (!match) throw new Error('not_found')
  const [, version, caseName] = match
  if (!CASE_PATTERN.test(caseName) || caseName.includes('..')) {
    throw new Error('not_found')
  }
  const manifest = await readJson(path.join(reviewRoot, 'review-manifest.json'))
  if (manifest.contract_version !== 'reader-review-manifest-v1') {
    throw new Error('not_found')
  }
  const entry = manifest.cases?.[caseName]
  if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
    throw new Error('not_found')
  }
  const expectedValue = entry[`${version}_url`]
  if (typeof expectedValue !== 'string') throw new Error('not_found')
  const expected = new URL(expectedValue, `http://${HOST}`).pathname
  if (expected !== pathname) throw new Error('not_found')
  return await safeFile(
    reviewRoot,
    path.join(reviewRoot, version, caseName, 'reader.html'),
  )
}


async function createHandler({ reviewRoot, repositoryRoot, metadata }) {
  const reviewPage = path.join(repositoryRoot, 'review', 'index.html')
  return async (request, response) => {
    if (request.method !== 'GET') {
      send(response, 405, 'Method Not Allowed\n', 'text/plain; charset=utf-8')
      return
    }
    let pathname
    try {
      pathname = decodeURIComponent(
        new URL(request.url ?? '/', `http://${HOST}`).pathname,
      )
    } catch {
      notFound(response)
      return
    }
    try {
      if (pathname === '/health') {
        send(
          response,
          200,
          `${JSON.stringify(metadata)}\n`,
          'application/json; charset=utf-8',
        )
        return
      }
      if (pathname === '/review' || pathname === '/review/index.html') {
        send(
          response,
          200,
          await fs.readFile(reviewPage),
          'text/html; charset=utf-8',
        )
        return
      }
      if (pathname === '/api/review-manifest') {
        const manifestPath = await safeFile(
          reviewRoot,
          path.join(reviewRoot, 'review-manifest.json'),
        )
        send(
          response,
          200,
          await fs.readFile(manifestPath),
          'application/json; charset=utf-8',
        )
        return
      }
      if (pathname.startsWith('/content/')) {
        const file = await contentFile(reviewRoot, pathname)
        send(
          response,
          200,
          await fs.readFile(file),
          'text/html; charset=utf-8',
        )
        return
      }
      notFound(response)
    } catch {
      notFound(response)
    }
  }
}


async function removeOwnedMetadata(serverFile, metadata) {
  try {
    const current = await readJson(serverFile)
    if (current.pid === metadata.pid && current.token === metadata.token) {
      await fs.rm(serverFile, { force: true })
    }
  } catch {
    // Missing or replaced ownership metadata is not ours to remove.
  }
}


async function main() {
  const options = parseArgs(process.argv.slice(2))
  const session = await readJson(path.join(options.reviewRoot, 'session.json'))
  if (
    session.contract_version !== 'reader-review-session-v1'
    || session.session_id !== options.sessionId
  ) {
    throw new Error('review_session_invalid')
  }
  const serverFile = path.join(options.reviewRoot, 'server.json')
  const server = http.createServer()
  const listening = await new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off('listening', onListening)
      reject(error)
    }
    const onListening = () => {
      server.off('error', onError)
      resolve(server.address())
    }
    server.once('error', onError)
    server.once('listening', onListening)
    server.listen(options.port, HOST)
  }).catch((error) => {
    if (error?.code === 'EADDRINUSE') {
      const conflict = new Error('review_port_in_use')
      conflict.cause = error
      throw conflict
    }
    throw error
  })
  const metadata = {
    contract_version: SERVER_CONTRACT,
    pid: process.pid,
    port: listening.port,
    repository_root: options.repositoryRoot,
    session_id: options.sessionId,
    started_at: new Date().toISOString(),
    token: options.token,
  }
  server.on(
    'request',
    await createHandler({
      reviewRoot: options.reviewRoot,
      repositoryRoot: options.repositoryRoot,
      metadata,
    }),
  )
  await atomicWriteJson(serverFile, metadata)
  process.stdout.write(`${JSON.stringify(metadata)}\n`)

  let closing = false
  const shutdown = () => {
    if (closing) return
    closing = true
    server.close(async () => {
      await removeOwnedMetadata(serverFile, metadata)
      process.exit(0)
    })
  }
  process.once('SIGINT', shutdown)
  process.once('SIGTERM', shutdown)
}


main().catch((error) => {
  const errorCode = error?.message === 'review_port_in_use'
    ? 'review_port_in_use'
    : 'review_server_failed'
  process.stderr.write(`${JSON.stringify({ error_code: errorCode })}\n`)
  process.exitCode = 1
})
