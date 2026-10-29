import { useMemo, useState } from 'react'
import type { TokenConnectRequest } from '../services/tokenConnectBridge'

export const MAX_CONNECTION_NAME_LENGTH = 80
export const MAX_CONNECTION_DESCRIPTION_LENGTH = 500

export function nameProblem(name: string, existingNames: string[]): string | null {
  const trimmed = name.trim()
  if (!trimmed) return 'Give this connection a name.'
  if (trimmed.length > MAX_CONNECTION_NAME_LENGTH) return `Use ${MAX_CONNECTION_NAME_LENGTH} characters or fewer.`
  if (existingNames.some((existing) => existing.localeCompare(trimmed, undefined, { sensitivity: 'accent' }) === 0)) {
    return `A connection named ${trimmed} already exists. Choose a different name, such as adding the account or purpose.`
  }
  return null
}

export function AgentTokenConnectModal({
  request,
  isWorking,
  errorMessage,
  onConnect,
  onCancel,
}: {
  request: TokenConnectRequest
  isWorking: boolean
  errorMessage: string | null
  onConnect: (friendlyName: string, description: string | undefined, token: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(request.friendlyName)
  const [description, setDescription] = useState(request.description ?? '')
  const [token, setToken] = useState('')
  const problem = useMemo(() => nameProblem(name, request.existingNames), [name, request.existingNames])
  const canSubmit = !isWorking && problem === null && token.trim().length > 0

  function handleSubmit() {
    if (!canSubmit) return
    const trimmedDescription = description.trim()
    onConnect(
      name.trim(),
      trimmedDescription ? trimmedDescription.slice(0, MAX_CONNECTION_DESCRIPTION_LENGTH) : undefined,
      token,
    )
  }

  return (
    <div className="connections-add-modal" role="dialog" aria-modal="true" aria-label="Connect a service with a token">
      <h3 className="connections-add-modal-title">Connect a service with a token</h3>
      <p className="connections-add-modal-subtitle">
        Basil will send this token only to the host below. The assistant never sees it, and it is not written to the chat.
      </p>

      <div className="connections-add-form" aria-label="Destination">
        <p className="connections-add-modal-section-title">Basil will send the token only to</p>
        <p className="connections-starter-button-name">{request.host}</p>
        <p className="connections-starter-button-description">{request.serverUrl}</p>
      </div>

      {request.alreadyConnectedAs ? (
        <p className="connections-settings-banner connections-settings-banner-info" role="status">
          You already have {request.alreadyConnectedAs} connected at this address. This adds a second connection, for example another account or workspace, so give it a name that tells them apart.
        </p>
      ) : null}

      <label className="connections-add-form-field">
        Name
        <input
          type="text"
          aria-label="Connection name"
          placeholder="For example Hugging Face (work)"
          value={name}
          disabled={isWorking}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      {problem && (name.trim() || request.alreadyConnectedAs) ? (
        <p className="connections-settings-error" role="alert">{problem}</p>
      ) : null}

      <label className="connections-context-field">
        Description (optional)
        <input
          type="text"
          aria-label="Connection description"
          placeholder="What this connection is for"
          value={description}
          disabled={isWorking}
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <p className="connections-add-form-hint">
        Shown in Settings and read by the agent, so it can choose the right connection when you have several for one service.
      </p>

      <label className="connections-add-form-field">
        Token or API key
        <input
          type="password"
          aria-label="Token or API key"
          placeholder="Paste the token here"
          value={token}
          disabled={isWorking}
          onChange={(event) => setToken(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSubmit()
          }}
        />
      </label>

      {errorMessage ? <p className="connections-settings-error" role="alert">{errorMessage}</p> : null}
      {isWorking ? <p className="connections-panel-status" role="status">Checking the token with {request.host}…</p> : null}

      <div className="connections-add-form-actions">
        <button type="button" className="secondary-button" disabled={isWorking} onClick={onCancel}>Cancel</button>
        <button type="button" className="primary-button" disabled={!canSubmit} onClick={handleSubmit}>Connect</button>
      </div>
    </div>
  )
}
