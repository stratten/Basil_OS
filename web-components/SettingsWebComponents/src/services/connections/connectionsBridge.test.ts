// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  notifyConnectionsSettingsReady,
  onConnectionsEvent,
  requestCancelGitHubDeviceFlow,
  requestCheckConnectionStatus,
  requestChooseWorkspaceFolder,
  requestCreateProviderProfile,
  requestCreateWorkspaceGrant,
  requestDeleteConnection,
  requestLoadProviderProfileConfiguration,
  requestOpenExternalUrl,
  requestReconnectConnection,
  requestRefreshCallLog,
  requestRefreshTools,
  requestRegisterManualToken,
  requestRemoveProviderProfile,
  requestReplaceConnectionToken,
  requestRevokeWorkspaceGrant,
  requestSetProviderProfileEnabled,
  requestStartGitHubDeviceFlow,
  requestStartOAuth,
  requestStartSlackOAuth,
  requestUpdateConnectionMetadata,
  requestUpdatePolicy,
  requestUpdateProviderProfile,
  requestUpdateWorkspaceGrant,
} from './connectionsBridge'

let postMessage: ReturnType<typeof vi.fn>

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilConnectionsSettingsBridge: { postMessage } } }
})

describe('connectionsBridge', () => {
  it('sends reactReady with protocolVersion 1', () => {
    notifyConnectionsSettingsReady()
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('sends requestStartOAuth with server details', () => {
    const id = requestStartOAuth('https://mcp.linear.app/sse', 'Linear', 'Issue tracking')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestStartOAuth', requestId: id, serverUrl: 'https://mcp.linear.app/sse', friendlyName: 'Linear', description: 'Issue tracking' })
  })

  it('sends requestStartSlackOAuth with server details', () => {
    const id = requestStartSlackOAuth('https://slack.com/mcp', 'Slack', undefined)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestStartSlackOAuth', requestId: id, serverUrl: 'https://slack.com/mcp', friendlyName: 'Slack', description: undefined })
  })

  it('sends requestStartGitHubDeviceFlow with server details', () => {
    const id = requestStartGitHubDeviceFlow('https://api.githubcopilot.com/mcp', 'GitHub', undefined)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestStartGitHubDeviceFlow', requestId: id, serverUrl: 'https://api.githubcopilot.com/mcp', friendlyName: 'GitHub', description: undefined })
  })

  it('sends requestCancelGitHubDeviceFlow with only a requestId', () => {
    const id = requestCancelGitHubDeviceFlow()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCancelGitHubDeviceFlow', requestId: id })
  })

  it('sends requestOpenExternalUrl with the url', () => {
    const id = requestOpenExternalUrl('https://github.com/login/device')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestOpenExternalUrl', requestId: id, url: 'https://github.com/login/device' })
  })

  it('sends requestRegisterManualToken with the bearer token', () => {
    const id = requestRegisterManualToken('https://api.githubcopilot.com/mcp', 'GitHub', 'ghp_secret', 'My token')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRegisterManualToken', requestId: id, serverUrl: 'https://api.githubcopilot.com/mcp', friendlyName: 'GitHub', description: 'My token', bearerToken: 'ghp_secret' })
  })

  it('sends requestDeleteConnection with the connectionId', () => {
    const id = requestDeleteConnection('conn-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestDeleteConnection', requestId: id, connectionId: 'conn-1' })
  })

  it('sends requestRefreshTools with the connectionId', () => {
    const id = requestRefreshTools('conn-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRefreshTools', requestId: id, connectionId: 'conn-1' })
  })

  it('sends requestUpdateConnectionMetadata with the new fields', () => {
    const id = requestUpdateConnectionMetadata('conn-1', 'GitHub (work)', 'Work account')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdateConnectionMetadata', requestId: id, connectionId: 'conn-1', friendlyName: 'GitHub (work)', description: 'Work account' })
  })

  it('sends requestCheckConnectionStatus with the connectionId', () => {
    const id = requestCheckConnectionStatus('conn-1')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestCheckConnectionStatus', requestId: id, connectionId: 'conn-1' })
  })

  it('sends requestReconnectConnection with the connectionId', () => {
    const id = requestReconnectConnection('conn-1')
    expect(id).toMatch(/^reconnectConnection-/)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestReconnectConnection', requestId: id, connectionId: 'conn-1' })
  })

  it('sends requestReplaceConnectionToken with the connectionId and token', () => {
    const id = requestReplaceConnectionToken('conn-1', 'new-secret')
    expect(id).toMatch(/^replaceConnectionToken-/)
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestReplaceConnectionToken', requestId: id, connectionId: 'conn-1', bearerToken: 'new-secret' })
  })

  it('sends requestUpdatePolicy with the tool and policy', () => {
    const id = requestUpdatePolicy('conn-1', 'create_issue', 'ask')
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestUpdatePolicy', requestId: id, connectionId: 'conn-1', toolName: 'create_issue', policy: 'ask' })
  })

  it('sends requestRefreshCallLog with only a requestId', () => {
    const id = requestRefreshCallLog()
    expect(postMessage).toHaveBeenCalledWith({ type: 'requestRefreshCallLog', requestId: id })
  })

  it('requestCreateProviderProfile posts the profile fields', () => {
    requestCreateProviderProfile('Codex CLI', ['/usr/local/bin/codex'], ['OPENAI_API_KEY'], 'api-key', 'desc', ['hint'])
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestCreateProviderProfile', displayName: 'Codex CLI', launchArgv: ['/usr/local/bin/codex'] }))
  })

  it('requestUpdateProviderProfile posts the expected revision', () => {
    requestUpdateProviderProfile('p1', 3, 'Codex CLI', ['/bin/codex'], [], undefined, undefined, [])
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateProviderProfile', profileId: 'p1', expectedRevision: 3 }))
  })

  it('requestSetProviderProfileEnabled posts enabled flag', () => {
    requestSetProviderProfileEnabled('p1', 3, true)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestSetProviderProfileEnabled', profileId: 'p1', enabled: true }))
  })

  it('requestRemoveProviderProfile posts the profile id', () => {
    requestRemoveProviderProfile('p1', 3)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRemoveProviderProfile', profileId: 'p1', expectedRevision: 3 }))
  })

  it('requestLoadProviderProfileConfiguration posts the profile id', () => {
    requestLoadProviderProfileConfiguration('p1')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestLoadProviderProfileConfiguration', profileId: 'p1' }))
  })

  it('requestChooseWorkspaceFolder posts the profile id', () => {
    requestChooseWorkspaceFolder('p1')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestChooseWorkspaceFolder', profileId: 'p1' }))
  })

  it('requestCreateWorkspaceGrant posts the grant fields', () => {
    requestCreateWorkspaceGrant('p1', '/Users/me/proj', 'My Project', undefined, [])
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestCreateWorkspaceGrant', profileId: 'p1', canonicalWorkspaceRoot: '/Users/me/proj' }))
  })

  it('requestUpdateWorkspaceGrant posts the expected revision', () => {
    requestUpdateWorkspaceGrant('p1', 'g1', 2, 'My Project', undefined, [])
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestUpdateWorkspaceGrant', profileId: 'p1', grantId: 'g1', expectedRevision: 2 }))
  })

  it('requestRevokeWorkspaceGrant posts the grant id', () => {
    requestRevokeWorkspaceGrant('p1', 'g1', 2)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'requestRevokeWorkspaceGrant', profileId: 'p1', grantId: 'g1', expectedRevision: 2 }))
  })

  it('queues events until a live handler subscribes, then flushes them in order', () => {
    window.basilConnectionsSettings!.onEvent({ type: 'loadError', message: 'boom' })
    const received: string[] = []
    const unsubscribe = onConnectionsEvent((event) => received.push(event.type))
    expect(received).toEqual(['loadError'])
    window.basilConnectionsSettings!.onEvent({ type: 'intentResult', requestId: 'x', status: 'success' })
    expect(received).toEqual(['loadError', 'intentResult'])
    unsubscribe()
  })
})
