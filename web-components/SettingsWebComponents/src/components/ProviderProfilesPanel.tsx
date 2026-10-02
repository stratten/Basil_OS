import { useEffect, useState } from 'react'
import PresenceRegion from '@shared/PresenceRegion'
import {
  requestChooseWorkspaceFolder,
  requestLoadProviderProfileConfiguration,
  requestRemoveProviderProfile,
  requestRevokeWorkspaceGrant,
  requestSetProviderProfileEnabled,
} from '../services/connectionsBridge'
import { AddProviderProfileModal } from './AddProviderProfileModal'
import { ProviderProfileRow } from './ProviderProfileRow'
import { WorkspaceGrantModal } from './WorkspaceGrantModal'
import type {
  ConnectionsProviderProfileConfigurationEvent,
  ConnectionsWorkspaceFolderChosenEvent,
  ProviderProfileConfiguration,
  ProviderProfileSummary,
  ProviderProfileWorkspaceGrant,
} from '../types'

interface ProviderProfilesPanelProps {
  providerProfiles: ProviderProfileSummary[]
  isLoading: boolean
  isMutating: boolean
  statusMessage: string | null
  errorMessage: string | null
  pendingId: string | null
  requestError: string | null
  onTrackRequest: (id: string) => void
  configEvent: ConnectionsProviderProfileConfigurationEvent | null
  onConsumeConfigEvent: () => void
  folderEvent: ConnectionsWorkspaceFolderChosenEvent | null
  onConsumeFolderEvent: () => void
}

interface GrantContext {
  profile: ProviderProfileSummary
  existingGrant: ProviderProfileWorkspaceGrant | null
  canonicalWorkspaceRoot: string
}

export function ProviderProfilesPanel({
  providerProfiles,
  isLoading,
  isMutating,
  statusMessage,
  errorMessage,
  pendingId,
  requestError,
  onTrackRequest,
  configEvent,
  onConsumeConfigEvent,
  folderEvent,
  onConsumeFolderEvent,
}: ProviderProfilesPanelProps) {
  const disabled = pendingId !== null || isMutating
  const [showAddModal, setShowAddModal] = useState(false)
  const [editingProfile, setEditingProfile] = useState<ProviderProfileConfiguration | null>(null)
  const [pendingEditRequestId, setPendingEditRequestId] = useState<string | null>(null)
  const [grantContext, setGrantContext] = useState<GrantContext | null>(null)
  const [pendingFolderRequestId, setPendingFolderRequestId] = useState<string | null>(null)
  const [activeModalRequestId, setActiveModalRequestId] = useState<string | null>(null)

  useEffect(() => {
    if (!configEvent || configEvent.requestId !== pendingEditRequestId) return
    setPendingEditRequestId(null)
    onConsumeConfigEvent()
    if (configEvent.configuration) setEditingProfile(configEvent.configuration)
  }, [configEvent, pendingEditRequestId, onConsumeConfigEvent])

  useEffect(() => {
    if (!folderEvent || folderEvent.requestId !== pendingFolderRequestId) return
    setPendingFolderRequestId(null)
    onConsumeFolderEvent()
    if (folderEvent.canonicalWorkspaceRoot) {
      const profile = providerProfiles.find((candidate) => candidate.id === folderEvent.profileId)
      if (profile) setGrantContext({ profile, existingGrant: null, canonicalWorkspaceRoot: folderEvent.canonicalWorkspaceRoot })
    }
  }, [folderEvent, pendingFolderRequestId, onConsumeFolderEvent, providerProfiles])

  useEffect(() => {
    if (!activeModalRequestId || pendingId === activeModalRequestId) return
    setActiveModalRequestId(null)
    if (!requestError) {
      setShowAddModal(false)
      setEditingProfile(null)
      setGrantContext(null)
    }
  }, [pendingId, activeModalRequestId, requestError])

  function trackAndWatch(id: string) {
    onTrackRequest(id)
    setActiveModalRequestId(id)
  }

  function handleEdit(profile: ProviderProfileSummary) {
    const id = requestLoadProviderProfileConfiguration(profile.id)
    onTrackRequest(id)
    setPendingEditRequestId(id)
  }

  function handleToggleEnabled(profile: ProviderProfileSummary) {
    onTrackRequest(requestSetProviderProfileEnabled(profile.id, profile.revision, profile.status !== 'enabled'))
  }

  function handleAddWorkspace(profile: ProviderProfileSummary) {
    const id = requestChooseWorkspaceFolder(profile.id)
    onTrackRequest(id)
    setPendingFolderRequestId(id)
  }

  function handleRemove(profile: ProviderProfileSummary) {
    onTrackRequest(requestRemoveProviderProfile(profile.id, profile.revision))
  }

  function handleEditGrant(profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) {
    setGrantContext({ profile, existingGrant: grant, canonicalWorkspaceRoot: grant.canonicalWorkspaceRoot })
  }

  function handleRevokeGrant(profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) {
    onTrackRequest(requestRevokeWorkspaceGrant(profile.id, grant.id, grant.revision))
  }

  return (
    <section className="provider-profiles-panel" aria-labelledby="provider-profiles-heading">
      <div className="connections-panel-header">
        <div>
          <h3 id="provider-profiles-heading">Provider Profiles</h3>
          <p className="provider-profiles-subtitle">
            Register an installed ACP runtime and authorize local workspace roots. Registration never starts a provider.
          </p>
        </div>
        <button type="button" className="connections-add-toggle" disabled={disabled} onClick={() => setShowAddModal(true)}>
          + Add Provider
        </button>
      </div>

      {statusMessage && <p className="connections-panel-status" role="status">{statusMessage}</p>}
      {errorMessage && <p className="provider-profile-validation-error" role="alert">{errorMessage}</p>}

      {isLoading && providerProfiles.length === 0 ? (
        <p className="connections-panel-status" role="status">Loading provider profiles...</p>
      ) : providerProfiles.length === 0 ? (
        <div className="connections-empty-state">
          <p className="connections-empty-state-title">No provider profiles yet.</p>
          <p className="connections-empty-state-body">Add an installed ACP runtime to begin configuring future provider catalog eligibility.</p>
        </div>
      ) : (
        <div className="connections-list basil-refresh-region" aria-busy={isLoading ? true : undefined}>
          {providerProfiles.map((profile) => (
            <ProviderProfileRow
              key={profile.id}
              profile={profile}
              disabled={disabled}
              onEdit={handleEdit}
              onToggleEnabled={handleToggleEnabled}
              onAddWorkspace={handleAddWorkspace}
              onRemove={handleRemove}
              onEditGrant={handleEditGrant}
              onRevokeGrant={handleRevokeGrant}
            />
          ))}
        </div>
      )}

      <PresenceRegion visible={showAddModal} className="connections-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        <AddProviderProfileModal configuration={null} disabled={disabled} onTrackRequest={trackAndWatch} onDismiss={() => setShowAddModal(false)} />
      </PresenceRegion>
      <PresenceRegion visible={editingProfile !== null} className="connections-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        {editingProfile && (
          <AddProviderProfileModal configuration={editingProfile} disabled={disabled} onTrackRequest={trackAndWatch} onDismiss={() => setEditingProfile(null)} />
        )}
      </PresenceRegion>
      <PresenceRegion visible={grantContext !== null} className="connections-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        {grantContext && (
          <WorkspaceGrantModal
            profile={grantContext.profile}
            existingGrant={grantContext.existingGrant}
            canonicalWorkspaceRoot={grantContext.canonicalWorkspaceRoot}
            disabled={disabled}
            onTrackRequest={trackAndWatch}
            onDismiss={() => setGrantContext(null)}
          />
        )}
      </PresenceRegion>
    </section>
  )
}
