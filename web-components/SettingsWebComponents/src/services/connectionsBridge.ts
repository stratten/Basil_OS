import { postToSwiftHandler } from '@shared/swiftBridge'
import type { ConnectionsNativeEvent } from '../types'

type OutgoingConnectionsMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'requestStartOAuth'; requestId: string; serverUrl: string; friendlyName: string; description?: string }
  | { type: 'requestStartSlackOAuth'; requestId: string; serverUrl: string; friendlyName: string; description?: string }
  | { type: 'requestStartGitHubDeviceFlow'; requestId: string; serverUrl: string; friendlyName: string; description?: string }
  | { type: 'requestCancelGitHubDeviceFlow'; requestId: string }
  | { type: 'requestOpenExternalUrl'; requestId: string; url: string }
  | { type: 'requestRegisterManualToken'; requestId: string; serverUrl: string; friendlyName: string; description?: string; bearerToken: string }
  | { type: 'requestDeleteConnection'; requestId: string; connectionId: string }
  | { type: 'requestRefreshTools'; requestId: string; connectionId: string }
  | { type: 'requestUpdateConnectionMetadata'; requestId: string; connectionId: string; friendlyName: string; description: string }
  | { type: 'requestCheckConnectionStatus'; requestId: string; connectionId: string }
  | { type: 'requestReconnectConnection'; requestId: string; connectionId: string }
  | { type: 'requestReplaceConnectionToken'; requestId: string; connectionId: string; bearerToken: string }
  | { type: 'requestUpdatePolicy'; requestId: string; connectionId: string; toolName: string; policy: string }
  | { type: 'requestRefreshCallLog'; requestId: string }
  | { type: 'requestCreateProviderProfile'; requestId: string; displayName: string; launchArgv: string[]; environmentAllowlist: string[]; authenticationMethodId?: string; description?: string; routingHints: string[] }
  | { type: 'requestUpdateProviderProfile'; requestId: string; profileId: string; expectedRevision: number; displayName: string; launchArgv: string[]; environmentAllowlist: string[]; authenticationMethodId?: string; description?: string; routingHints: string[] }
  | { type: 'requestSetProviderProfileEnabled'; requestId: string; profileId: string; expectedRevision: number; enabled: boolean }
  | { type: 'requestRemoveProviderProfile'; requestId: string; profileId: string; expectedRevision: number }
  | { type: 'requestLoadProviderProfileConfiguration'; requestId: string; profileId: string }
  | { type: 'requestChooseWorkspaceFolder'; requestId: string; profileId: string }
  | { type: 'requestCreateWorkspaceGrant'; requestId: string; profileId: string; canonicalWorkspaceRoot: string; workspaceLabel: string; description?: string; routingHints: string[] }
  | { type: 'requestUpdateWorkspaceGrant'; requestId: string; profileId: string; grantId: string; expectedRevision: number; workspaceLabel: string; description?: string; routingHints: string[] }
  | { type: 'requestRevokeWorkspaceGrant'; requestId: string; profileId: string; grantId: string; expectedRevision: number }

declare global {
  interface Window {
    basilConnectionsSettings?: {
      onEvent: (event: ConnectionsNativeEvent) => void
    }
  }
}

type EventHandler = (event: ConnectionsNativeEvent) => void

let queuedEvents: ConnectionsNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: ConnectionsNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilConnectionsSettings = { onEvent: dispatch }

export function onConnectionsEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach(handler)
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingConnectionsMessage) {
  postToSwiftHandler('basilConnectionsSettingsBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyConnectionsSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function requestStartOAuth(serverUrl: string, friendlyName: string, description?: string): string {
  const id = requestId('startOAuth')
  postMessage({ type: 'requestStartOAuth', requestId: id, serverUrl, friendlyName, description })
  return id
}

export function requestStartSlackOAuth(serverUrl: string, friendlyName: string, description?: string): string {
  const id = requestId('startSlackOAuth')
  postMessage({ type: 'requestStartSlackOAuth', requestId: id, serverUrl, friendlyName, description })
  return id
}

export function requestStartGitHubDeviceFlow(serverUrl: string, friendlyName: string, description?: string): string {
  const id = requestId('startGitHubDeviceFlow')
  postMessage({ type: 'requestStartGitHubDeviceFlow', requestId: id, serverUrl, friendlyName, description })
  return id
}

export function requestCancelGitHubDeviceFlow(): string {
  const id = requestId('cancelGitHubDeviceFlow')
  postMessage({ type: 'requestCancelGitHubDeviceFlow', requestId: id })
  return id
}

export function requestOpenExternalUrl(url: string): string {
  const id = requestId('openExternalUrl')
  postMessage({ type: 'requestOpenExternalUrl', requestId: id, url })
  return id
}

export function requestRegisterManualToken(serverUrl: string, friendlyName: string, bearerToken: string, description?: string): string {
  const id = requestId('registerManualToken')
  postMessage({ type: 'requestRegisterManualToken', requestId: id, serverUrl, friendlyName, description, bearerToken })
  return id
}

export function requestDeleteConnection(connectionId: string): string {
  const id = requestId('deleteConnection')
  postMessage({ type: 'requestDeleteConnection', requestId: id, connectionId })
  return id
}

export function requestRefreshTools(connectionId: string): string {
  const id = requestId('refreshTools')
  postMessage({ type: 'requestRefreshTools', requestId: id, connectionId })
  return id
}

export function requestUpdateConnectionMetadata(connectionId: string, friendlyName: string, description: string): string {
  const id = requestId('updateConnectionMetadata')
  postMessage({ type: 'requestUpdateConnectionMetadata', requestId: id, connectionId, friendlyName, description })
  return id
}

export function requestCheckConnectionStatus(connectionId: string): string {
  const id = requestId('checkConnectionStatus')
  postMessage({ type: 'requestCheckConnectionStatus', requestId: id, connectionId })
  return id
}

export function requestReconnectConnection(connectionId: string): string {
  const id = requestId('reconnectConnection')
  postMessage({ type: 'requestReconnectConnection', requestId: id, connectionId })
  return id
}

export function requestReplaceConnectionToken(connectionId: string, bearerToken: string): string {
  const id = requestId('replaceConnectionToken')
  postMessage({ type: 'requestReplaceConnectionToken', requestId: id, connectionId, bearerToken })
  return id
}

export function requestUpdatePolicy(connectionId: string, toolName: string, policy: string): string {
  const id = requestId('updatePolicy')
  postMessage({ type: 'requestUpdatePolicy', requestId: id, connectionId, toolName, policy })
  return id
}

export function requestRefreshCallLog(): string {
  const id = requestId('refreshCallLog')
  postMessage({ type: 'requestRefreshCallLog', requestId: id })
  return id
}

export function requestCreateProviderProfile(
  displayName: string,
  launchArgv: string[],
  environmentAllowlist: string[],
  authenticationMethodId: string | undefined,
  description: string | undefined,
  routingHints: string[],
): string {
  const id = requestId('createProviderProfile')
  postMessage({ type: 'requestCreateProviderProfile', requestId: id, displayName, launchArgv, environmentAllowlist, authenticationMethodId, description, routingHints })
  return id
}

export function requestUpdateProviderProfile(
  profileId: string,
  expectedRevision: number,
  displayName: string,
  launchArgv: string[],
  environmentAllowlist: string[],
  authenticationMethodId: string | undefined,
  description: string | undefined,
  routingHints: string[],
): string {
  const id = requestId('updateProviderProfile')
  postMessage({ type: 'requestUpdateProviderProfile', requestId: id, profileId, expectedRevision, displayName, launchArgv, environmentAllowlist, authenticationMethodId, description, routingHints })
  return id
}

export function requestSetProviderProfileEnabled(profileId: string, expectedRevision: number, enabled: boolean): string {
  const id = requestId('setProviderProfileEnabled')
  postMessage({ type: 'requestSetProviderProfileEnabled', requestId: id, profileId, expectedRevision, enabled })
  return id
}

export function requestRemoveProviderProfile(profileId: string, expectedRevision: number): string {
  const id = requestId('removeProviderProfile')
  postMessage({ type: 'requestRemoveProviderProfile', requestId: id, profileId, expectedRevision })
  return id
}

export function requestLoadProviderProfileConfiguration(profileId: string): string {
  const id = requestId('loadProviderProfileConfiguration')
  postMessage({ type: 'requestLoadProviderProfileConfiguration', requestId: id, profileId })
  return id
}

export function requestChooseWorkspaceFolder(profileId: string): string {
  const id = requestId('chooseWorkspaceFolder')
  postMessage({ type: 'requestChooseWorkspaceFolder', requestId: id, profileId })
  return id
}

export function requestCreateWorkspaceGrant(
  profileId: string,
  canonicalWorkspaceRoot: string,
  workspaceLabel: string,
  description: string | undefined,
  routingHints: string[],
): string {
  const id = requestId('createWorkspaceGrant')
  postMessage({ type: 'requestCreateWorkspaceGrant', requestId: id, profileId, canonicalWorkspaceRoot, workspaceLabel, description, routingHints })
  return id
}

export function requestUpdateWorkspaceGrant(
  profileId: string,
  grantId: string,
  expectedRevision: number,
  workspaceLabel: string,
  description: string | undefined,
  routingHints: string[],
): string {
  const id = requestId('updateWorkspaceGrant')
  postMessage({ type: 'requestUpdateWorkspaceGrant', requestId: id, profileId, grantId, expectedRevision, workspaceLabel, description, routingHints })
  return id
}

export function requestRevokeWorkspaceGrant(profileId: string, grantId: string, expectedRevision: number): string {
  const id = requestId('revokeWorkspaceGrant')
  postMessage({ type: 'requestRevokeWorkspaceGrant', requestId: id, profileId, grantId, expectedRevision })
  return id
}
