import { useEffect, useState } from 'react'
import type { ConnectionsSettingsFields } from '../types'
import { AddConnectionModal } from './AddConnectionModal'
import { ConnectionRow } from './ConnectionRow'
import { ConnectionSignInProgress } from './ConnectionSignInProgress'

interface ConnectionsPanelProps {
  fields: ConnectionsSettingsFields
  pendingId: string | null
  onTrackRequest: (id: string) => void
}

export function ConnectionsPanel({ fields, pendingId, onTrackRequest }: ConnectionsPanelProps) {
  const [showAddModal, setShowAddModal] = useState(false)
  const [hiddenPendingFlowName, setHiddenPendingFlowName] = useState<string | null>(null)
  const disabled = pendingId !== null

  useEffect(() => {
    if (!fields.pendingFlowFriendlyName) setHiddenPendingFlowName(null)
  }, [fields.pendingFlowFriendlyName])

  function dismissAddModal() {
    setHiddenPendingFlowName(fields.pendingFlowFriendlyName)
    setShowAddModal(false)
  }

  return (
    <section className="connections-panel" aria-labelledby="connections-servers-heading">
      <div className="connections-panel-header">
        <h3 id="connections-servers-heading">Connected Servers</h3>
        <button
          type="button"
          className="connections-add-toggle"
          disabled={disabled}
          onClick={() => setShowAddModal(true)}
        >
          + Add Connection
        </button>
      </div>

      {!showAddModal && (
        <ConnectionSignInProgress
          fields={fields}
          onTrackRequest={onTrackRequest}
          onContinueInBackground={() => setHiddenPendingFlowName(fields.pendingFlowFriendlyName)}
          showPendingFlow={fields.pendingFlowFriendlyName !== hiddenPendingFlowName}
        />
      )}

      {fields.isLoading ? (
        <p className="connections-panel-status" role="status">Loading connections...</p>
      ) : fields.connections.length === 0 ? (
        <div className="connections-empty-state">
          <p className="connections-empty-state-title">No connections yet.</p>
          <p className="connections-empty-state-body">Click &ldquo;+ Add Connection&rdquo; to authorize Basil to call a remote MCP server on your behalf.</p>
        </div>
      ) : (
        <div className="connections-list">
          {fields.connections.map((connection) => (
            <ConnectionRow
              key={connection.id}
              connection={connection}
              pendingId={pendingId}
              onTrackRequest={onTrackRequest}
            />
          ))}
        </div>
      )}

      {showAddModal && (
        <div className="connections-modal-overlay" role="presentation">
          <AddConnectionModal
            fields={fields}
            pendingId={pendingId}
            onTrackRequest={onTrackRequest}
            onDismiss={dismissAddModal}
          />
        </div>
      )}
    </section>
  )
}
