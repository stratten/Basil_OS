import { useEffect, useMemo, useState } from 'react'
import PresenceRegion from '@shared/PresenceRegion'
import { requestCheckConnectionStatus } from '../services/connectionsBridge'
import type { ConnectionsSettingsFields, MCPConnection, MCPStarterServer } from '../types'
import { AddConnectionModal } from './AddConnectionModal'
import { ConnectionRow } from './ConnectionRow'
import { ConnectionSignInProgress } from './ConnectionSignInProgress'
import { useAfterRequest } from './useAfterRequest'

interface ConnectionsPanelProps {
  fields: ConnectionsSettingsFields
  pendingId: string | null
  onTrackRequest: (id: string) => void
  onTrackPolicyRequest?: (id: string) => void
}

function hostnameOf(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase()
  } catch {
    return url.toLowerCase()
  }
}

export function connectionProviderLabel(connection: MCPConnection, starterServers: readonly MCPStarterServer[]): string {
  const host = hostnameOf(connection.serverUrl)
  const starter = starterServers.find((candidate) => hostnameOf(candidate.serverUrl) === host)
  if (starter) return starter.friendlyName
  if (connection.serverName?.trim()) return connection.serverName.trim()
  return host || connection.friendlyName
}

function compareLocale(left: string, right: string): number {
  return left.localeCompare(right, undefined, { sensitivity: 'base' })
}

export function sortConnectionsByProvider(
  connections: readonly MCPConnection[],
  starterServers: readonly MCPStarterServer[],
): MCPConnection[] {
  return [...connections].sort((left, right) => {
    const provider = compareLocale(
      connectionProviderLabel(left, starterServers),
      connectionProviderLabel(right, starterServers),
    )
    if (provider !== 0) return provider
    const name = compareLocale(left.friendlyName, right.friendlyName)
    if (name !== 0) return name
    return left.id.localeCompare(right.id)
  })
}

export function ConnectionsPanel({ fields, pendingId, onTrackRequest, onTrackPolicyRequest }: ConnectionsPanelProps) {
  const [showAddModal, setShowAddModal] = useState(false)
  const [hiddenPendingFlowName, setHiddenPendingFlowName] = useState<string | null>(null)
  const disabled = pendingId !== null
  const runAfterRequest = useAfterRequest(pendingId)
  const sortedConnections = useMemo(
    () => sortConnectionsByProvider(fields.connections, fields.starterServers),
    [fields.connections, fields.starterServers],
  )

  useEffect(() => {
    if (!fields.pendingFlowFriendlyName) setHiddenPendingFlowName(null)
  }, [fields.pendingFlowFriendlyName])

  function dismissAddModal() {
    setHiddenPendingFlowName(fields.pendingFlowFriendlyName)
    setShowAddModal(false)
  }

  function checkAllStatuses() {
    const remainingIds = sortedConnections.map((connection) => connection.id)
    const startNext = (ids: string[]) => {
      if (ids.length === 0) return
      const [head, ...rest] = ids
      const requestId = requestCheckConnectionStatus(head)
      onTrackRequest(requestId)
      if (rest.length > 0) {
        runAfterRequest(requestId, () => startNext(rest))
      }
    }
    startNext(remainingIds)
  }

  return (
    <section className="connections-panel" aria-labelledby="connections-servers-heading">
      <div className="connections-panel-header">
        <h3 id="connections-servers-heading">Connected Servers</h3>
        <div className="connections-panel-header-actions">
          {sortedConnections.length > 0 && (
            <button
              type="button"
              className="connections-add-toggle"
              disabled={disabled}
              onClick={checkAllStatuses}
            >
              Check Status for All
            </button>
          )}
          <button
            type="button"
            className="connections-add-toggle"
            disabled={disabled}
            onClick={() => setShowAddModal(true)}
          >
            + Add Connection
          </button>
        </div>
      </div>

      {!showAddModal && (
        <ConnectionSignInProgress
          fields={fields}
          onTrackRequest={onTrackRequest}
          onContinueInBackground={() => setHiddenPendingFlowName(fields.pendingFlowFriendlyName)}
          showPendingFlow={fields.pendingFlowFriendlyName !== hiddenPendingFlowName}
        />
      )}

      {fields.isLoading && fields.connections.length === 0 ? (
        <p className="connections-panel-status" role="status">Loading connections...</p>
      ) : fields.connections.length === 0 ? (
        <div className="connections-empty-state">
          <p className="connections-empty-state-title">No connections yet.</p>
          <p className="connections-empty-state-body">Click &ldquo;+ Add Connection&rdquo; to authorize Basil to call a remote MCP server on your behalf.</p>
        </div>
      ) : (
        <div className="connections-list basil-refresh-region" aria-busy={fields.isLoading ? true : undefined}>
          {sortedConnections.map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              pendingId={pendingId}
              onTrackRequest={onTrackRequest}
              onTrackPolicyRequest={onTrackPolicyRequest}
              gmailTransport={fields.gmailTransport}
              gmailTransportPinnedByEnvironment={fields.gmailTransportPinnedByEnvironment}
              dateDisplayStyle={fields.dateDisplayStyle}
            />
          ))}
        </div>
      )}

      <PresenceRegion visible={showAddModal} className="connections-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        <AddConnectionModal
          fields={fields}
          pendingId={pendingId}
          onTrackRequest={onTrackRequest}
          onDismiss={dismissAddModal}
        />
      </PresenceRegion>
    </section>
  )
}
