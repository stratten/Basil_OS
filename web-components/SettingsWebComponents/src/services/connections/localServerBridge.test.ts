// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  requestCancelPrepareLocalServer,
  requestInstallLocalServerRequirement,
  requestPrepareLocalServer,
  requestRefreshLocalServerStatus,
  requestRegisterLocalServer,
  requestSaveLocalServerSecrets,
  requestSetCompanionStartWithBasil,
  requestStartCompanion,
  requestStopCompanion,
} from './connectionsBridge'
import type { LocalServerRegistration } from '../../types'

let postMessage: ReturnType<typeof vi.fn>

const REGISTRATION: LocalServerRegistration = {
  friendlyName: 'WhatsApp',
  command: '/usr/local/bin/uv',
  args: ['run', 'main.py'],
  env: { MODE: 'local' },
  secretEnv: ['API_KEY'],
  companion: null,
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
})

describe('local server bridge messages', () => {
  it('sends the definition and the secret values together in one registration message', () => {
    const id = requestRegisterLocalServer(REGISTRATION, { API_KEY: 'k-1' })

    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestRegisterLocalServer',
      requestId: id,
      registration: REGISTRATION,
      secretValues: { API_KEY: 'k-1' },
    })
    expect(id.startsWith('registerLocalServer-')).toBe(true)
  })

  it('sends one message per background-program control and secret save', () => {
    const start = requestStartCompanion('c-1')
    const stop = requestStopCompanion('c-1')
    const toggle = requestSetCompanionStartWithBasil('c-1', false)
    const save = requestSaveLocalServerSecrets('c-1', { API_KEY: 'k-2' })

    expect(postMessage.mock.calls.map(([message]) => message)).toEqual([
      { type: 'requestStartCompanion', requestId: start, connectionId: 'c-1' },
      { type: 'requestStopCompanion', requestId: stop, connectionId: 'c-1' },
      { type: 'requestSetCompanionStartWithBasil', requestId: toggle, connectionId: 'c-1', startWithBasil: false },
      { type: 'requestSaveLocalServerSecrets', requestId: save, connectionId: 'c-1', secretValues: { API_KEY: 'k-2' } },
    ])
    expect(new Set([start, stop, toggle, save]).size).toBe(4)
  })
})

describe('local server setup bridge messages', () => {
  it('sends one message per setup control, carrying the exact install command', () => {
    const refresh = requestRefreshLocalServerStatus('c-1')
    const prepare = requestPrepareLocalServer('c-1')
    const cancel = requestCancelPrepareLocalServer('c-1')
    const install = requestInstallLocalServerRequirement('c-1', 'Go', 'brew install go')

    expect(postMessage.mock.calls.map(([message]) => message)).toEqual([
      { type: 'requestRefreshLocalServerStatus', requestId: refresh, connectionId: 'c-1' },
      { type: 'requestPrepareLocalServer', requestId: prepare, connectionId: 'c-1' },
      { type: 'requestCancelPrepareLocalServer', requestId: cancel, connectionId: 'c-1' },
      { type: 'requestInstallLocalServerRequirement', requestId: install, connectionId: 'c-1', name: 'Go', command: 'brew install go' },
    ])
  })
})
