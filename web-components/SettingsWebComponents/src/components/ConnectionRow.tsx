import { useEffect, useState } from 'react'
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron'
import PresenceRegion from '@shared/PresenceRegion'
import TokenizedSelect from '@shared/TokenizedSelect'
import { formatTimestampForDisplay } from '@shared/timestampDisplay'
import {
  requestCheckConnectionStatus,
  requestDeleteConnection,
  requestReconnectConnection,
  requestRefreshTools,
  requestReplaceConnectionToken,
  requestSetGmailTransport,
  requestUpdateConnectionMetadata,
  requestUpdatePolicy,
} from '../services/connectionsBridge'
import type { DateDisplayStyle, GmailTransport, MCPConnection } from '../types'
import { GmailTransportToggle, gmailTransportSummary } from './GmailTransportToggle'
import { useAfterRequest } from './useAfterRequest'

interface ConnectionRowProps {
  connection: MCPConnection
  pendingId: string | null
  onTrackRequest: (id: string) => void
  onTrackPolicyRequest?: (id: string) => void
  gmailTransport?: GmailTransport
  gmailTransportPinnedByEnvironment?: boolean
  dateDisplayStyle?: DateDisplayStyle
}

const POLICY_OPTIONS: ReadonlyArray<{ id: string; label: string }> = [
  { id: 'always_allow', label: 'Always allow' },
  { id: 'always_ask', label: 'Always ask' },
  { id: 'never_allow', label: 'Never allow' },
]

function statusLabel(status: string | null): string {
  switch (status) {
    case 'healthy':
      return 'Healthy'
    case 'needs_reconnect':
      return 'Needs reconnect'
    case 'token_unavailable':
      return 'Token unavailable'
    case 'error':
      return 'Status check failed'
    default:
      return 'Status not checked yet'
  }
}

function statusClassName(status: string | null): string {
  if (status === 'healthy') return 'connections-row-status connections-row-status-healthy'
  if (status === 'needs_reconnect' || status === 'token_unavailable' || status === 'error') {
    return 'connections-row-status connections-row-status-error'
  }
  return 'connections-row-status connections-row-status-unknown'
}

function requiresReconnect(status: string | null): boolean {
  return status === 'needs_reconnect' || status === 'token_unavailable'
}

export function ConnectionRow({
  connection,
  pendingId,
  onTrackRequest,
  onTrackPolicyRequest,
  gmailTransport,
  gmailTransportPinnedByEnvironment = false,
  dateDisplayStyle = 'relative',
}: ConnectionRowProps) {
  const isGmail = gmailTransport !== undefined && connection.serverUrl.includes('gmailmcp.googleapis.com')
  const [editedTransport, setEditedTransport] = useState<GmailTransport>(gmailTransport ?? 'direct')
  const runAfterRequest = useAfterRequest(pendingId)
  const [isExpanded, setIsExpanded] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editedName, setEditedName] = useState(connection.friendlyName)
  const [editedDescription, setEditedDescription] = useState(connection.description ?? '')
  const [isReplacingToken, setIsReplacingToken] = useState(false)
  const [replacementToken, setReplacementToken] = useState('')
  const [policyDrafts, setPolicyDrafts] = useState<Record<string, string>>({})
  const disabled = pendingId !== null

  useEffect(() => {
    setPolicyDrafts({})
  }, [connection.tools])
  const needsReconnect = requiresReconnect(connection.lastConnectionStatus)
  const trimmedReplacementToken = replacementToken.trim()

  function beginEditing() {
    setEditedName(connection.friendlyName)
    setEditedDescription(connection.description ?? '')
    setEditedTransport(gmailTransport ?? 'direct')
    setIsEditing(true)
  }

  function saveEditing() {
    const trimmedName = editedName.trim()
    if (trimmedName.length === 0) return
    const metadataRequestId = requestUpdateConnectionMetadata(connection.id, trimmedName, editedDescription.trim())
    onTrackRequest(metadataRequestId)
    if (isGmail && !gmailTransportPinnedByEnvironment && editedTransport !== gmailTransport) {
      const chosenTransport = editedTransport
      runAfterRequest(metadataRequestId, () => onTrackRequest(requestSetGmailTransport(chosenTransport)))
    }
    setIsEditing(false)
  }

  function reconnect() {
    if (connection.authKind === 'manual_token') {
      setReplacementToken('')
      setIsReplacingToken(true)
      return
    }
    onTrackRequest(requestReconnectConnection(connection.id))
  }

  function cancelTokenReplacement() {
    setReplacementToken('')
    setIsReplacingToken(false)
  }

  function saveReplacementToken() {
    if (trimmedReplacementToken.length === 0) return
    onTrackRequest(requestReplaceConnectionToken(connection.id, trimmedReplacementToken))
    setReplacementToken('')
    setIsReplacingToken(false)
  }

  return (
    <div className="connections-row">
      <div className="connections-row-summary">
        <button
          type="button"
          className="connections-row-expand"
          aria-expanded={isExpanded}
          aria-label={isExpanded ? 'Collapse tool policies' : 'Expand tool policies'}
          onClick={() => setIsExpanded((current) => !current)}
        >
          <ExecutionDisclosureChevron expanded={isExpanded} color="var(--text-secondary)" />
        </button>

        <div className="connections-row-body">
          {isEditing ? (
            <div className="connections-row-edit-fields">
              <input
                type="text"
                className="connections-row-edit-name"
                value={editedName}
                disabled={disabled}
                onChange={(event) => setEditedName(event.target.value)}
              />
              <input
                type="text"
                className="connections-row-edit-description"
                placeholder="Description or workspace context"
                value={editedDescription}
                disabled={disabled}
                onChange={(event) => setEditedDescription(event.target.value)}
              />
              {isGmail && (
                <GmailTransportToggle
                  value={editedTransport}
                  pinnedByEnvironment={gmailTransportPinnedByEnvironment}
                  disabled={disabled}
                  onChange={setEditedTransport}
                />
              )}
            </div>
          ) : (
            <>
              <p className="connections-row-name">{connection.friendlyName}</p>
              {connection.description && <p className="connections-row-description">{connection.description}</p>}
              <p className="connections-row-url">{connection.serverUrl}</p>
              <p className={statusClassName(connection.lastConnectionStatus)}>
                <span className="connections-row-status-dot" />
                {statusLabel(connection.lastConnectionStatus)}
                {connection.lastConnectionCheckAt && (
                  <span className="connections-row-status-checked-at">Checked {formatTimestampForDisplay(connection.lastConnectionCheckAt, dateDisplayStyle)}</span>
                )}
                {connection.lastSuccessfulUseAt && (
                  <span className="connections-row-status-checked-at">Last used successfully {formatTimestampForDisplay(connection.lastSuccessfulUseAt, dateDisplayStyle)}</span>
                )}
                {isGmail && (
                  <span className="connections-row-transport">{gmailTransportSummary(gmailTransport ?? 'direct', gmailTransportPinnedByEnvironment)}</span>
                )}
              </p>
              {isReplacingToken && (
                <input
                  type="password"
                  className="connections-row-edit-token"
                  aria-label={`New bearer token for ${connection.friendlyName}`}
                  placeholder="Paste a new bearer token"
                  value={replacementToken}
                  disabled={disabled}
                  onChange={(event) => setReplacementToken(event.target.value)}
                />
              )}
            </>
          )}
        </div>

        <div className="connections-row-actions">
          {isEditing ? (
            <>
              <button type="button" className="connections-row-action-button" disabled={disabled} onClick={() => setIsEditing(false)}>Cancel</button>
              <button type="button" className="connections-row-action-button connections-row-action-primary" disabled={disabled || editedName.trim().length === 0} onClick={saveEditing}>Save</button>
            </>
          ) : isReplacingToken ? (
            <>
              <button type="button" className="connections-row-action-button" disabled={disabled} onClick={cancelTokenReplacement}>Cancel</button>
              <button
                type="button"
                className="connections-row-action-button connections-row-action-primary"
                disabled={disabled || trimmedReplacementToken.length === 0}
                onClick={saveReplacementToken}
              >
                Save Token
              </button>
            </>
          ) : (
            <>
              <button type="button" className="connections-row-action-button" disabled={disabled} onClick={beginEditing}>Edit</button>
              {needsReconnect ? (
                <button
                  type="button"
                  className="connections-row-action-button connections-row-action-primary"
                  disabled={disabled}
                  onClick={reconnect}
                >
                  Reconnect
                </button>
              ) : (
                <button
                  type="button"
                  className="connections-row-action-button"
                  disabled={disabled}
                  onClick={() => onTrackRequest(requestCheckConnectionStatus(connection.id))}
                >
                  Check Status
                </button>
              )}
              <button
                type="button"
                className="connections-row-action-button"
                disabled={disabled}
                onClick={() => onTrackRequest(requestRefreshTools(connection.id))}
              >
                Refresh Tools
              </button>
              <button
                type="button"
                className="connections-row-action-button connections-row-action-danger"
                disabled={disabled}
                onClick={() => onTrackRequest(requestDeleteConnection(connection.id))}
              >
                Remove
              </button>
            </>
          )}
        </div>
      </div>

      <PresenceRegion visible={isExpanded} className="basil-presence" settleWithoutTransition>
        <div className="connections-row-tools">
          {connection.tools.length === 0 ? (
            <p className="connections-row-tools-empty">No tools cached yet. Click "Refresh Tools" to fetch the live catalog from the server.</p>
          ) : (
            connection.tools.map((tool) => {
              const policy = policyDrafts[tool.name] ?? tool.policy
              return (
              <div key={tool.name} className="connections-tool-row" data-policy={policy}>
                <div className="connections-tool-row-body">
                  <span className="connections-tool-row-name">
                    {tool.name}
                    {tool.isReadOnlyHint && <span className="connections-tool-row-readonly-badge">read-only</span>}
                  </span>
                  {tool.description && <span className="connections-tool-row-description">{tool.description}</span>}
                </div>
                <TokenizedSelect
                  className="connections-tool-row-policy"
                  value={policy}
                  ariaLabel={`Policy for ${tool.name}`}
                  onValueChange={(nextPolicy) => {
                    setPolicyDrafts((drafts) => ({ ...drafts, [tool.name]: nextPolicy }))
                    const trackPolicy = onTrackPolicyRequest ?? onTrackRequest
                    trackPolicy(requestUpdatePolicy(connection.id, tool.name, nextPolicy))
                  }}
                  options={POLICY_OPTIONS.map((option) => ({ value: option.id, label: option.label }))}
                />
              </div>
              )
            })
          )}
        </div>
      </PresenceRegion>
    </div>
  )
}
