import type { Config } from './config.js'
import { extractJson, loginScansci, runScansci } from './cli.js'

export interface InstitutionSchool {
  name: string
  province: string
  type: string
}

async function wrapped(config: Config, command: string, input?: unknown) {
  const result = await runScansci(config.scansciExe, [command], config, {
    useWrap: true,
    timeoutMs: 60_000,
    ...(input === undefined ? {} : { input: JSON.stringify(input) }),
  })
  const json = extractJson(result.stdout)
  if (result.exitCode !== 0 || !json) throw new Error(result.stderr || command + '_failed')
  return json
}

export const institutionDependencies = {
  async schools(config: Config): Promise<InstitutionSchool[]> {
    const result = await wrapped(config, 'schools-json')
    return Array.isArray(result.schools) ? result.schools as InstitutionSchool[] : []
  },
  async status(config: Config): Promise<Record<string, unknown>> {
    return wrapped(config, 'session-status-json')
  },
  async select(config: Config, school: string): Promise<Record<string, unknown>> {
    return wrapped(config, 'school-set-json', { school })
  },
  async login(config: Config): Promise<Record<string, unknown>> {
    const result = await loginScansci(config.scansciExe, 'webvpn')
    if (result.exitCode !== 0) throw new Error(result.stderr || 'institution_login_failed')
    return { status: 'completed' }
  },
}
