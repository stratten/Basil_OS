import { useEffect, useRef, useState } from 'react'
import {
  requestRefreshLocalServerStatus,
  requestRefreshTools,
  requestSaveLocalServerSecrets,
  requestSetCompanionStartWithBasil,
  requestStartCompanion,
  requestStopCompanion,
} from '../../services/connections/connectionsBridge'
import type { CompanionInfo, CompanionStatus, LocalServerInfo } from '../../types'
import { LocalServerLink } from './LocalServerLink'
import { LocalServerSetup } from './LocalServerSetup'
import { namesMissingValues, secretValuesFor } from './localServerForm'

/** How often the page asks for fresh state while a setup step, a start, or a step that needs the person is in progress. */
export const LOCAL_SERVER_POLL_MILLISECONDS = 3000

interface LocalServerPanelProps {
  connectionId: string
  localServer: LocalServerInfo
  disabled: boolean
  onTrackRequest: (id: string) => void
  /** How many tools the connection has cached. When the program reports it is linked and there are none, the page asks for them once. */
  toolCount?: number
}

/** True while something about the server is still changing on its own, so the page should keep asking for fresh state. */
export function localServerIsChanging(localServer: LocalServerInfo): boolean {
  const companion = localServer.companion
  const phase = companion?.health?.phase
  return Boolean(localServer.install?.active) || companion?.status === 'starting' || phase === 'starting' || phase === 'needs_action'
}

function useLocalServerPolling(connectionId: string, changing: boolean) {
  useEffect(() => {
    if (!changing) return undefined
    const timer = window.setInterval(() => {
      requestRefreshLocalServerStatus(connectionId)
    }, LOCAL_SERVER_POLL_MILLISECONDS)
    return () => window.clearInterval(timer)
  }, [connectionId, changing])
}

function useToolsOnceLinked(connectionId: string, localServer: LocalServerInfo, toolCount: number | undefined, onTrackRequest: (id: string) => void) {
  const asked = useRef(false)
  const linked = localServer.companion?.health?.phase === 'ready'
  useEffect(() => {
    if (!linked) {
      asked.current = false
      return
    }
    if (toolCount === 0 && !asked.current) {
      asked.current = true
      onTrackRequest(requestRefreshTools(connectionId))
    }
  }, [linked, toolCount, connectionId, onTrackRequest])
}

export function companionStatusLabel(companion: CompanionInfo): string {
  switch (companion.status) {
    case 'running':
      return companion.port ? `Running on port ${companion.port}` : 'Running'
    case 'starting':
      return 'Starting...'
    case 'stopping':
      return 'Stopping...'
    case 'failed':
      return 'Failed'
    case 'needs_secrets':
      return 'Needs secret values'
    default:
      return 'Stopped'
  }
}

function statusTone(status: CompanionStatus): 'ok' | 'error' | 'neutral' {
  if (status === 'running') return 'ok'
  if (status === 'failed' || status === 'needs_secrets') return 'error'
  return 'neutral'
}

/** Every declared secret name that has no saved value, the server's first and then the background program's, each once. */
export function missingSecretNames(localServer: LocalServerInfo): string[] {
  const names: string[] = []
  for (const secret of [...localServer.secretEnv, ...(localServer.companion?.secretEnv ?? [])]) {
    if (!secret.saved && !names.includes(secret.name)) names.push(secret.name)
  }
  return names
}

function savedSecretNames(localServer: LocalServerInfo): string[] {
  const names: string[] = []
  for (const secret of [...localServer.secretEnv, ...(localServer.companion?.secretEnv ?? [])]) {
    if (secret.saved && !names.includes(secret.name)) names.push(secret.name)
  }
  return names
}

function CompanionBlock({ connectionId, companion, disabled, onTrackRequest }: {
  connectionId: string
  companion: CompanionInfo
  disabled: boolean
  onTrackRequest: (id: string) => void
}) {
  const isActive = companion.status === 'running' || companion.status === 'starting'
  const tone = statusTone(companion.status)
  return (
    <div className="connections-local-companion">
      <p className="connections-local-line">
        <span className="connections-local-label">Background program</span>
        <span className={`connections-local-status connections-local-status-${tone}`}>{companionStatusLabel(companion)}</span>
      </p>
      <p className="connections-local-line">
        <code className="connections-local-code">{companion.commandSummary}</code>
      </p>
      {companion.restartCount > 0 && companion.status === 'running' && (
        <p className="connections-local-hint">
          It stopped unexpectedly and Basil restarted it {companion.restartCount} {companion.restartCount === 1 ? 'time' : 'times'}.
        </p>
      )}
      {companion.lastError && companion.status !== 'running' && companion.status !== 'stopped' && (
        <p className="connections-local-error" role="alert">{companion.lastError}</p>
      )}
      {companion.status === 'failed' && companion.logTail && (
        <pre className="connections-local-log" aria-label="Recent output of the background program" tabIndex={0}>{companion.logTail}</pre>
      )}
      <div className="connections-local-actions">
        {isActive ? (
          <button
            type="button"
            className="connections-row-action-button"
            disabled={disabled}
            onClick={() => onTrackRequest(requestStopCompanion(connectionId))}
          >
            Stop
          </button>
        ) : (
          <button
            type="button"
            className="connections-row-action-button"
            disabled={disabled || companion.status === 'needs_secrets' || companion.status === 'stopping'}
            onClick={() => onTrackRequest(requestStartCompanion(connectionId))}
          >
            Start
          </button>
        )}
        <label className="connections-local-check">
          <input
            type="checkbox"
            checked={companion.startWithBasil}
            disabled={disabled}
            onChange={(event) => onTrackRequest(requestSetCompanionStartWithBasil(connectionId, event.target.checked))}
          />
          Start whenever Basil starts
        </label>
      </div>
    </div>
  )
}

export function LocalServerPanel({ connectionId, localServer, disabled, onTrackRequest, toolCount }: LocalServerPanelProps) {
  useLocalServerPolling(connectionId, localServerIsChanging(localServer))
  useToolsOnceLinked(connectionId, localServer, toolCount, onTrackRequest)
  const [secretValues, setSecretValues] = useState<Record<string, string>>({})
  const missing = missingSecretNames(localServer)
  const saved = savedSecretNames(localServer)
  const canSave = missing.length > 0 && namesMissingValues(missing, secretValues).length === 0

  function saveSecrets() {
    if (!canSave) return
    onTrackRequest(requestSaveLocalServerSecrets(connectionId, secretValuesFor(missing, secretValues)))
    setSecretValues({})
  }

  return (
    <div className="connections-local-panel">
      <p className="connections-local-line">
        <span className="connections-local-label">Runs</span>
        <code className="connections-local-code">{localServer.commandSummary}</code>
      </p>
      {localServer.sourceUrl && (
        <p className="connections-local-line">
          <span className="connections-local-label">From</span>
          <span className="connections-local-text">{localServer.sourceUrl}</span>
        </p>
      )}
      {saved.length > 0 && (
        <p className="connections-local-line">
          <span className="connections-local-label">In your Keychain</span>
          <span className="connections-local-text">{saved.join(', ')}</span>
        </p>
      )}
      {missing.length > 0 && (
        <div className="connections-local-secrets" role="group" aria-label="Missing secret values">
          <p className="connections-local-text">
            It needs {missing.join(', ')} before it can start. The values go straight to your Keychain and are never shown again.
          </p>
          {missing.map((name) => (
            <label key={name} className="connections-local-secret-field">
              {`Value for ${name}`}
              <input
                type="password"
                name={`secret-${name}`}
                autoComplete="off"
                value={secretValues[name] ?? ''}
                disabled={disabled}
                onChange={(event) => setSecretValues((current) => ({ ...current, [name]: event.target.value }))}
              />
            </label>
          ))}
          <div className="connections-local-actions">
            <button
              type="button"
              className="connections-row-action-button connections-row-action-primary"
              disabled={disabled || !canSave}
              onClick={saveSecrets}
            >
              Save and start
            </button>
          </div>
        </div>
      )}
      {localServer.install && (
        <LocalServerSetup connectionId={connectionId} install={localServer.install} disabled={disabled} onTrackRequest={onTrackRequest} />
      )}
      {localServer.companion && (
        <CompanionBlock connectionId={connectionId} companion={localServer.companion} disabled={disabled} onTrackRequest={onTrackRequest} />
      )}
      {localServer.companion?.health && <LocalServerLink health={localServer.companion.health} now={Date.now()} />}
    </div>
  )
}
