import { useState } from 'react'
import { requestCreateWorkspaceGrant, requestUpdateWorkspaceGrant } from '../../services/connections/connectionsBridge'
import { cleanedStringList, optionalTrimmed, StringListEditor } from '../StringListEditor'
import type { ProviderProfileSummary, ProviderProfileWorkspaceGrant } from '../../types'
import { SettingsModalCard } from '../modal/SettingsModalCard'

interface WorkspaceGrantModalProps {
  profile: ProviderProfileSummary
  existingGrant: ProviderProfileWorkspaceGrant | null
  canonicalWorkspaceRoot: string
  disabled: boolean
  onTrackRequest: (id: string) => void
  onDismiss: () => void
}

function lastPathComponent(path: string): string {
  const trimmed = path.replace(/\/+$/, '')
  const segments = trimmed.split('/')
  return segments[segments.length - 1] || trimmed
}

export function WorkspaceGrantModal({
  profile,
  existingGrant,
  canonicalWorkspaceRoot,
  disabled,
  onTrackRequest,
  onDismiss,
}: WorkspaceGrantModalProps) {
  const [workspaceLabel, setWorkspaceLabel] = useState(existingGrant?.workspaceLabel ?? lastPathComponent(canonicalWorkspaceRoot))
  const [description, setDescription] = useState(existingGrant?.description ?? '')
  const [routingHints, setRoutingHints] = useState<string[]>(existingGrant?.routingHints ?? [])

  const trimmedLabel = workspaceLabel.trim()
  const isValid = trimmedLabel.length > 0

  function handleSave() {
    if (!isValid) return
    const cleanedHints = cleanedStringList(routingHints)
    const desc = optionalTrimmed(description)
    if (existingGrant) {
      onTrackRequest(
        requestUpdateWorkspaceGrant(profile.id, existingGrant.id, existingGrant.revision, trimmedLabel, desc, cleanedHints),
      )
    } else {
      onTrackRequest(requestCreateWorkspaceGrant(profile.id, canonicalWorkspaceRoot, trimmedLabel, desc, cleanedHints))
    }
  }

  return (
    <SettingsModalCard
      title={existingGrant ? 'Edit Workspace Authorization' : 'Authorize Workspace'}
      ariaLabel="Workspace Authorization"
      subtitle={canonicalWorkspaceRoot}
      subtitleClassName="connections-workspace-grant-path"
      onClose={onDismiss}
    >

      <label className="connections-add-form-field">
        Workspace label
        <input type="text" value={workspaceLabel} disabled={disabled} onChange={(event) => setWorkspaceLabel(event.target.value)} />
      </label>

      <label className="connections-add-form-field">
        Description
        <textarea rows={3} value={description} disabled={disabled} onChange={(event) => setDescription(event.target.value)} />
      </label>

      <StringListEditor label="Routing hints" values={routingHints} placeholder="Hint" maxCount={8} disabled={disabled} onChange={setRoutingHints} />

      <div className="connections-add-form-actions">
        <button type="button" className="secondary-button" onClick={onDismiss}>Cancel</button>
        <button type="button" className="primary-button" disabled={disabled || !isValid} onClick={handleSave}>Save</button>
      </div>
    </SettingsModalCard>
  )
}
