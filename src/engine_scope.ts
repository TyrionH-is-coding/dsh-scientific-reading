import { AsyncLocalStorage } from 'node:async_hooks'

export interface EngineScope {
  instanceId: string
  scopeSessionId: string
  scopeFolderId: string
  scopePaperId?: string
  scopePaperRevision?: number
}

const context = new AsyncLocalStorage<Readonly<EngineScope>>()

/** 仅供可信宿主桥使用；不得把 scope 作为模型可填写的工具参数。 */
export function withEngineScope<T>(scope: EngineScope, action: () => T): T {
  if (['instanceId', 'scopeSessionId', 'scopeFolderId'].some(key =>
    typeof scope[key as keyof EngineScope] !== 'string' || !scope[key as keyof EngineScope])) {
    throw new Error('scope_invalid')
  }
  return context.run(Object.freeze({ ...scope }), action)
}

export function engineScopeEnvironment(): NodeJS.ProcessEnv {
  const scope = context.getStore()
  return { SR_SCOPE_CONTEXT: scope ? JSON.stringify(scope) : undefined }
}

/** 仅用于可信宿主解析真实会话绑定；业务操作仍必须继承当前作用域。 */
export function withoutEngineScope<T>(action: () => T): T {
  return context.exit(action)
}
