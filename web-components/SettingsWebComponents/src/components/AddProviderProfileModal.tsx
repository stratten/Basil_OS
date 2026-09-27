import { useState } from 'react'
import { requestCreateProviderProfile, requestUpdateProviderProfile } from '../services/connectionsBridge'
import { cleanedStringList, optionalTrimmed, StringListEditor } from './StringListEditor'
import type { ProviderProfileConfiguration } from '../types'

interface AddProviderProfileModalProps {
  configuration: ProviderProfileConfiguration | null
  disabled: boolean
  onTrackRequest: (id: string) => void
  onDismiss: () => void
}

export function AddProviderProfileModal({ configuration, disabled, onTrackRequest, onDismiss }: AddProviderProfileModalProps) {
  const [displayName, setDisplayName] = useState(configuration?.displayName ?? '')
  const [executablePath, setExecutablePath] = useState(configuration?.launchArgv[0] ?? '')
  const [arguments_, setArguments] = useState<string[]>(configuration?.launchArgv.slice(1) ?? [])
  const [environmentAllowlist, setEnvironmentAllowlist] = useState<string[]>(configuration?.environmentAllowlist ?? [])
  const [authenticationMethodId, setAuthenticationMethodId] = useState(configuration?.authenticationMethodId ?? '')
  const [description, setDescription] = useState(configuration?.description ?? '')
  const [routingHints, setRoutingHints] = useState<string[]>(configuration?.routingHints ?? [])

  const trimmedName = displayName.trim()
  const trimmedPath = executablePath.trim()
  const isValid = trimmedName.length > 0 && trimmedPath.length > 0

  function handleSave() {
    if (!isValid) return
    const launchArgv = [trimmedPath, ...cleanedStringList(arguments_)]
    const cleanedEnv = cleanedStringList(environmentAllowlist)
    const cleanedHints = cleanedStringList(routingHints)
    const authId = optionalTrimmed(authenticationMethodId)
    const desc = optionalTrimmed(description)
    if (configuration) {
      onTrackRequest(
        requestUpdateProviderProfile(configuration.id, configuration.revision, trimmedName, launchArgv, cleanedEnv, authId, desc, cleanedHints),
      )
    } else {
      onTrackRequest(requestCreateProviderProfile(trimmedName, launchArgv, cleanedEnv, authId, desc, cleanedHints))
    }
  }

  return (
    <div className="connections-add-modal" role="dialog" aria-modal="true" aria-label="Provider Profile">
      <h3 className="connections-add-modal-title">{configuration ? 'Edit Provider Profile' : 'Add Provider Profile'}</h3>
      <p className="connections-add-modal-subtitle">
        Use the absolute path to an installed ACP executable. Basil stores no provider credential and does not run the
        executable while saving.
      </p>

      <label className="connections-add-form-field">
        Display name
        <input type="text" value={displayName} disabled={disabled} onChange={(event) => setDisplayName(event.target.value)} />
      </label>

      <label className="connections-add-form-field">
        Absolute executable path
        <input type="text" value={executablePath} disabled={disabled} onChange={(event) => setExecutablePath(event.target.value)} />
      </label>

      <StringListEditor label="Arguments" values={arguments_} placeholder="Argument" maxCount={31} disabled={disabled} onChange={setArguments} />
      <StringListEditor label="Environment allowlist" values={environmentAllowlist} placeholder="Variable name" maxCount={32} disabled={disabled} onChange={setEnvironmentAllowlist} />

      <label className="connections-add-form-field">
        ACP authentication method ID (optional)
        <input type="text" value={authenticationMethodId} disabled={disabled} onChange={(event) => setAuthenticationMethodId(event.target.value)} />
      </label>
      <p className="connections-add-form-hint">
        For environment-backed authentication, enter an agent-advertised method ID such as api-key. Basil stores no
        credential value.
      </p>

      <label className="connections-add-form-field">
        Description
        <textarea rows={3} value={description} disabled={disabled} onChange={(event) => setDescription(event.target.value)} />
      </label>

      <StringListEditor label="Routing hints" values={routingHints} placeholder="Hint" maxCount={8} disabled={disabled} onChange={setRoutingHints} />

      <div className="connections-add-form-actions">
        <button type="button" className="secondary-button" onClick={onDismiss}>Cancel</button>
        <button type="button" className="primary-button" disabled={disabled || !isValid} onClick={handleSave}>Save</button>
      </div>
    </div>
  )
}
