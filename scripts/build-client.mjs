import { readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptPath = fileURLToPath(import.meta.url)
const rootPath = resolve(dirname(scriptPath), '..')

export const defaultSourcePath = resolve(rootPath, 'client', 'client.js')
export const defaultOutputPath = resolve(rootPath, 'lib', 'client.js')

export function normalizeClientSource(source) {
  return source.replace(/\r\n?/g, '\n')
}

function readSource(sourcePath) {
  return normalizeClientSource(readFileSync(sourcePath, 'utf8'))
}

export function checkClient({ sourcePath = defaultSourcePath, outputPath = defaultOutputPath } = {}) {
  const source = readSource(sourcePath)
  try {
    return readFileSync(outputPath, 'utf8') === source
  } catch (error) {
    if (error && error.code === 'ENOENT') return false
    throw error
  }
}

export function buildClient({ sourcePath = defaultSourcePath, outputPath = defaultOutputPath } = {}) {
  const source = readSource(sourcePath)
  const temporaryPath = `${outputPath}.${process.pid}.tmp`
  try {
    writeFileSync(temporaryPath, source, 'utf8')
    renameSync(temporaryPath, outputPath)
  } finally {
    rmSync(temporaryPath, { force: true })
  }
}

if (process.argv[1] && resolve(process.argv[1]) === scriptPath) {
  if (process.argv[2] === '--check') {
    if (checkClient()) {
      console.log('PASS: 客户端产物与规范源一致')
    } else {
      console.error('错误：客户端产物缺失或已过期，请运行 node scripts/build-client.mjs')
      process.exitCode = 1
    }
  } else if (process.argv.length === 2) {
    buildClient()
    console.log('PASS: 已生成客户端产物')
  } else {
    console.error('错误：仅支持 --check 参数')
    process.exitCode = 1
  }
}
