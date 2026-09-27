// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyPermissionsCommandSecurityReady,
  onPermissionsCommandSecurityEvent,
  requestAddWhitelistPattern,
  requestDeleteWhitelistPattern,
  requestUpdateApprovalSetting,
  requestUpdateWhitelistPattern,
} from './permissionsCommandSecurityBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilPermissionsCommandSecurityBridge: { postMessage } } }
})

describe('permissionsCommandSecurityBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyPermissionsCommandSecurityReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestUpdateApprovalSetting with the given patch', () => {
    const id = requestUpdateApprovalSetting({ safeExecutionMode: true })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestUpdateApprovalSetting',
      requestId: id,
      patch: { safeExecutionMode: true },
    })
  })

  it('sends requestAddWhitelistPattern with pattern fields', () => {
    const id = requestAddWhitelistPattern('git status', 'exact', 'Check status')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestAddWhitelistPattern',
      requestId: id,
      pattern: 'git status',
      patternType: 'exact',
      description: 'Check status',
    })
  })

  it('sends requestUpdateWhitelistPattern with the target id and fields', () => {
    const id = requestUpdateWhitelistPattern('pat-1', 'git ', 'prefix', 'Any git command')
    expect(postMessage).toHaveBeenCalledWith({
      type: 'requestUpdateWhitelistPattern',
      requestId: id,
      id: 'pat-1',
      pattern: 'git ',
      patternType: 'prefix',
      description: 'Any git command',
    })
  })

  it('sends requestDeleteWhitelistPattern with the target id', () => {
    const id = requestDeleteWhitelistPattern('pat-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteWhitelistPattern', requestId: id, id: 'pat-1' })
  })

  it('queues events until a handler subscribes, then delivers them in order', () => {
    window.basilPermissionsCommandSecurity!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onPermissionsCommandSecurityEvent((event) => {
      if (event.type === 'loadError') received.push(event.message)
    })
    expect(received).toEqual(['boom'])
    unsubscribe()
  })
})
