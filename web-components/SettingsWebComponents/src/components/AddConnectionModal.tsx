import { useEffect, useRef, useState } from 'react'
import {
  requestRegisterManualToken,
  requestStartGitHubDeviceFlow,
  requestStartOAuth,
  requestStartSlackOAuth,
} from '../services/connectionsBridge'
import type { ConnectionsSettingsFields, MCPStarterServer } from '../types'
import { ConnectionSignInProgress } from './ConnectionSignInProgress'

interface AddConnectionModalProps {
  fields: ConnectionsSettingsFields
  pendingId: string | null
  onTrackRequest: (id: string) => void
  onDismiss: () => void
}

// Starting a GitHub, Slack, or generic-OAuth flow only *opens the browser* --
// the actual connection doesn't complete until the user finishes consent
// there and the native side receives the `mcpConnectionCompleted` callback
// (GitHub instead polls in-process and is tracked via `githubDeviceFlow`
// below). So only the manual bearer-token form should close the moment its
// own request resolves; the other three stay open showing a waiting state
// until native clears `pendingFlowFriendlyName`/`githubDeviceFlow`.
type PendingKind = 'github' | 'slack' | 'default-starter' | 'manual'

function starterActionLabel(serverId: string): string {
  if (serverId === 'github') return 'Connect with GitHub'
  if (serverId === 'slack') return 'Connect with Slack'
  return 'Connect with OAuth'
}

export function AddConnectionModal({ fields, pendingId, onTrackRequest, onDismiss }: AddConnectionModalProps) {
  const [description, setDescription] = useState('')
  const [customName, setCustomName] = useState('')
  const [customUrl, setCustomUrl] = useState('')
  const [bearerToken, setBearerToken] = useState('')
  const [trackedRequestId, setTrackedRequestId] = useState<string | null>(null)
  const [trackedKind, setTrackedKind] = useState<PendingKind | null>(null)
  const disabled = pendingId !== null

  // The GitHub-start intent itself doesn't resolve until the whole device-flow
  // poll loop finishes, so closing here (once no error) is already correct
  // completion detection for that one case. Slack/generic-OAuth intents resolve
  // as soon as the browser opens -- far before the flow actually completes --
  // so they're deliberately excluded here and instead handled by the
  // `pendingFlowFriendlyName` effect below.
  useEffect(() => {
    if (!trackedRequestId || pendingId === trackedRequestId) return
    const closesUnconditionally = trackedKind === 'manual'
    const closesIfNoError = trackedKind === 'github' && !fields.errorMessage
    setTrackedRequestId(null)
    setTrackedKind(null)
    if (closesUnconditionally || closesIfNoError) onDismiss()
  }, [pendingId, trackedRequestId, trackedKind, fields.errorMessage, onDismiss])

  // Detects the moment native clears `pendingFlowFriendlyName` in its
  // `mcpConnectionCompleted` observer (unconditionally, on both success and
  // failure) -- the only reliable completion signal for Slack/generic-OAuth
  // flows, since it fires well after this modal's own start-intent already
  // resolved.
  const previousPendingFlowName = useRef<string | null>(null)
  useEffect(() => {
    const previous = previousPendingFlowName.current
    previousPendingFlowName.current = fields.pendingFlowFriendlyName
    if (previous && !fields.pendingFlowFriendlyName && !fields.errorMessage) {
      onDismiss()
    }
  }, [fields.pendingFlowFriendlyName, fields.errorMessage, onDismiss])

  function trimmedDescription(): string | undefined {
    const trimmed = description.trim()
    return trimmed.length > 0 ? trimmed : undefined
  }

  function track(id: string, kind: PendingKind) {
    onTrackRequest(id)
    setTrackedRequestId(id)
    setTrackedKind(kind)
  }

  function startStarterFlow(server: MCPStarterServer) {
    if (server.id === 'github') {
      track(requestStartGitHubDeviceFlow(server.serverUrl, server.friendlyName, trimmedDescription()), 'github')
      return
    }
    if (server.id === 'slack') {
      track(requestStartSlackOAuth(server.serverUrl, server.friendlyName, trimmedDescription()), 'slack')
      return
    }
    track(requestStartOAuth(server.serverUrl, server.friendlyName, trimmedDescription()), 'default-starter')
  }

  const trimmedName = customName.trim()
  const trimmedUrl = customUrl.trim()
  const trimmedToken = bearerToken.trim()
  const isManualValid = trimmedName.length > 0 && trimmedUrl.length > 0 && trimmedToken.length > 0

  function handleManualSubmit() {
    if (!isManualValid) return
    track(requestRegisterManualToken(trimmedUrl, trimmedName, trimmedToken, trimmedDescription()), 'manual')
  }

  return (
    <div className="connections-add-modal" role="dialog" aria-modal="true" aria-label="Add Connection">
      <h3 className="connections-add-modal-title">Add Connection</h3>
      <p className="connections-add-modal-subtitle">Pick a starter server, or register a custom bearer-token MCP server.</p>

      <label className="connections-context-field">
        Connection context (optional)
        <input
          type="text"
          placeholder="What will this connection be used for?"
          value={description}
          disabled={disabled}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>

      <ConnectionSignInProgress fields={fields} onTrackRequest={onTrackRequest} onContinueInBackground={onDismiss} />

      <h4 className="connections-add-modal-section-title">Starter Servers</h4>

      {fields.starterServers.length === 0 ? (
        <p className="connections-panel-status" role="status">Loading starter servers...</p>
      ) : (
        <div className="connections-starter-list">
          {fields.starterServers.map((server) => (
            <button
              key={server.id}
              type="button"
              className="connections-starter-button"
              disabled={disabled}
              onClick={() => startStarterFlow(server)}
            >
              <span className="connections-starter-button-body">
                <span className="connections-starter-button-name">{server.friendlyName}</span>
                <span className="connections-starter-button-description">{server.description}</span>
              </span>
              <span className="connections-starter-button-cta">{starterActionLabel(server.id)}</span>
            </button>
          ))}
        </div>
      )}

      <hr className="connections-add-modal-divider" />

      <div className="connections-add-form">
        <h4 className="connections-add-modal-section-title">Manual Bearer Token Server</h4>
        <label className="connections-add-form-field">
          Display name
          <input
            type="text"
            placeholder="e.g. Notion"
            value={customName}
            disabled={disabled}
            onChange={(event) => setCustomName(event.target.value)}
          />
        </label>
        <label className="connections-add-form-field">
          Server URL
          <input
            type="text"
            placeholder="https://..."
            value={customUrl}
            disabled={disabled}
            onChange={(event) => setCustomUrl(event.target.value)}
          />
        </label>
        <label className="connections-add-form-field">
          Bearer token
          <input
            type="password"
            placeholder="Paste your token"
            value={bearerToken}
            disabled={disabled}
            onChange={(event) => setBearerToken(event.target.value)}
          />
        </label>
        <p className="connections-add-form-hint">
          Use this for custom servers that require a bearer token and do not support OAuth Dynamic Client Registration.
        </p>
        <div className="connections-add-form-actions">
          <button type="button" className="secondary-button" onClick={onDismiss}>Cancel</button>
          <button type="button" className="primary-button" disabled={disabled || !isManualValid} onClick={handleManualSubmit}>
            Connect
          </button>
        </div>
      </div>
    </div>
  )
}
