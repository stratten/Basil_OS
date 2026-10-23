import type { ProviderProfileSummary, ProviderProfileWorkspaceGrant } from '../types'

interface ProviderProfileRowProps {
  profile: ProviderProfileSummary
  disabled: boolean
  onEdit: (profile: ProviderProfileSummary) => void
  onToggleEnabled: (profile: ProviderProfileSummary) => void
  onAddWorkspace: (profile: ProviderProfileSummary) => void
  onRemove: (profile: ProviderProfileSummary) => void
  onEditGrant: (profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void
  onRevokeGrant: (profile: ProviderProfileSummary, grant: ProviderProfileWorkspaceGrant) => void
}

function statusColorClass(profile: ProviderProfileSummary): string {
  if (profile.status === 'enabled') return profile.isStructurallyValid ? 'provider-profile-status-healthy' : 'provider-profile-status-warning'
  if (profile.status === 'disabled') return 'provider-profile-status-neutral'
  return 'provider-profile-status-danger'
}

function statusText(profile: ProviderProfileSummary): string {
  if (profile.status === 'enabled' && !profile.isStructurallyValid) return 'Enabled, invalid'
  return profile.status.charAt(0).toUpperCase() + profile.status.slice(1)
}

export function ProviderProfileRow({
  profile,
  disabled,
  onEdit,
  onToggleEnabled,
  onAddWorkspace,
  onRemove,
  onEditGrant,
  onRevokeGrant,
}: ProviderProfileRowProps) {
  const colorClass = statusColorClass(profile)
  return (
    <div className="provider-profile-row">
      <div className="provider-profile-row-header">
        <div className="provider-profile-row-identity">
          <span className="provider-profile-row-name">{profile.displayName}</span>
          {profile.description && <span className="provider-profile-row-description">{profile.description}</span>}
          <span className={`provider-profile-status ${colorClass}`}>
            <span className="provider-profile-status-dot" />
            {statusText(profile)}
          </span>
        </div>
        <span className={`provider-profile-capability-badge ${profile.hasObservedCapabilities ? 'observed' : 'unverified'}`}>
          {profile.hasObservedCapabilities ? 'Observed' : 'Unverified'}
        </span>
      </div>

      {profile.routingHints.length > 0 && (
        <p className="provider-profile-hints">Routing hints: {profile.routingHints.join(' \u00b7 ')}</p>
      )}
      {profile.validationError && <p className="provider-profile-validation-error">{profile.validationError}</p>}

      <div className="provider-profile-actions">
        <button type="button" className="secondary-button" disabled={disabled} onClick={() => onEdit(profile)}>Edit</button>
        <button type="button" className="secondary-button" disabled={disabled} onClick={() => onToggleEnabled(profile)}>
          {profile.status === 'enabled' ? 'Disable' : 'Enable'}
        </button>
        <button type="button" className="secondary-button" disabled={disabled} onClick={() => onAddWorkspace(profile)}>Add Workspace</button>
        <button type="button" className="connections-device-flow-cancel provider-profile-remove" disabled={disabled} onClick={() => onRemove(profile)}>Remove</button>
      </div>

      <div className="provider-profile-workspace-grants">
        <span className="provider-profile-workspace-grants-title">Authorized Workspaces</span>
        {profile.activeWorkspaceGrants.length === 0 ? (
          <p className="connections-row-tools-empty">No active workspace grant.</p>
        ) : (
          profile.activeWorkspaceGrants.map((grant) => (
            <div key={grant.id} className="provider-profile-grant-row">
              <div className="provider-profile-grant-body">
                <span className="provider-profile-grant-label">{grant.workspaceLabel}</span>
                <span className="provider-profile-grant-path">{grant.canonicalWorkspaceRoot}</span>
                {grant.description && <span className="provider-profile-grant-description">{grant.description}</span>}
                {grant.routingHints.length > 0 && (
                  <span className="provider-profile-hints">Routing hints: {grant.routingHints.join(' \u00b7 ')}</span>
                )}
              </div>
              <div className="provider-profile-grant-actions">
                <button type="button" className="secondary-button" disabled={disabled} onClick={() => onEditGrant(profile, grant)}>Edit</button>
                <button type="button" className="connections-device-flow-cancel" disabled={disabled} onClick={() => onRevokeGrant(profile, grant)}>Revoke</button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
