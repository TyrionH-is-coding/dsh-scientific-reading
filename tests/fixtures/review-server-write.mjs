// Test-only latch: expose the real metadata-write boundary without changing production code.
import fs from 'node:fs/promises'
import path from 'node:path'

const rename = fs.rename
fs.rename = async (from, to) => {
  if (path.basename(to) === 'server.json') {
    const metadata = JSON.parse(await fs.readFile(from, 'utf8'))
    const released = new Promise((resolve) => process.once('message', resolve))
    process.send({ type: 'metadata-write-blocked', port: metadata.port })
    await released
    process.disconnect()
    if (process.env.REVIEW_TEST_WRITE_FAILURE === '1') throw new Error('simulated_metadata_write_failure')
  }
  return rename(from, to)
}
