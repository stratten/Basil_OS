import {
  requestCancelPrepareLocalServer,
  requestInstallLocalServerRequirement,
  requestPrepareLocalServer,
} from '../../services/connections/connectionsBridge'
import type { LocalServerInstall, LocalServerInstallPhase } from '../../types'

interface LocalServerSetupProps {
  connectionId: string
  install: LocalServerInstall
  disabled: boolean
  onTrackRequest: (id: string) => void
}

export function installPhaseLabel(install: LocalServerInstall): string {
  const phase: LocalServerInstallPhase = install.phase
  switch (phase) {
    case 'ready':
      return 'Ready'
    case 'needs_requirement':
      return 'Needs an install'
    case 'failed':
      return 'Failed'
    case 'canceled':
      return 'Canceled'
    case 'idle':
      return 'Not set up yet'
    default:
      return 'Working...'
  }
}

function phaseTone(phase: LocalServerInstallPhase): 'ok' | 'error' | 'neutral' {
  if (phase === 'ready') return 'ok'
  if (phase === 'failed' || phase === 'needs_requirement') return 'error'
  return 'neutral'
}

/** What the server needs before it can run, with every program, address, hash, commit and command the recipe will use shown in full, so the person can see exactly what a button will do. */
export function LocalServerSetup({ connectionId, install, disabled, onTrackRequest }: LocalServerSetupProps) {
  const canPrepare = !install.active && !install.ready
  return (
    <div className="connections-local-companion" role="group" aria-label="Setup">
      <p className="connections-local-line">
        <span className="connections-local-label">Setup</span>
        <span className={`connections-local-status connections-local-status-${phaseTone(install.phase)}`}>{installPhaseLabel(install)}</span>
      </p>
      {install.message && (
        <p className={install.phase === 'failed' ? 'connections-local-error' : 'connections-local-text'} role={install.phase === 'failed' ? 'alert' : 'status'}>
          {install.message}
        </p>
      )}
      {install.requirements.length > 0 && (
        <ul className="connections-local-list" aria-label="Programs it needs">
          {install.requirements.map((requirement) => {
            const blocked = install.phase === 'needs_requirement' && install.requirement === requirement.name
            return (
              <li key={requirement.name} className="connections-local-list-item">
                <span className="connections-local-text">
                  <strong>{requirement.name}</strong>
                  {` - ${requirement.reason}`}
                </span>
                {requirement.installCommand ? (
                  <code className="connections-local-code">{requirement.installCommand}</code>
                ) : (
                  <span className="connections-local-hint">Basil cannot install this one. Install it yourself, then choose Prepare.</span>
                )}
                {blocked && install.canInstall && requirement.installCommand && (
                  <div className="connections-local-actions">
                    <button
                      type="button"
                      className="connections-row-action-button connections-row-action-primary"
                      disabled={disabled}
                      aria-label={`Install ${requirement.name} by running ${requirement.installCommand}`}
                      onClick={() => onTrackRequest(requestInstallLocalServerRequirement(connectionId, requirement.name, requirement.installCommand ?? ''))}
                    >
                      {`Install ${requirement.name}`}
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      {install.artifacts.length > 0 && (
        <ul className="connections-local-list" aria-label="Files it puts in place">
          {install.artifacts.map((artifact) => (
            <li key={artifact.name} className="connections-local-list-item">
              <span className="connections-local-text">
                <strong>{artifact.name}</strong>
                {` at ${artifact.expects} - `}
                <span className={`connections-local-status connections-local-status-${artifact.ready ? 'ok' : 'neutral'}`}>{artifact.ready ? 'in place' : 'not yet'}</span>
              </span>
              {artifact.ready ? null : (
                <ol className="connections-local-sources" aria-label={`Ways Basil gets ${artifact.name}, in the order it tries them`}>
                  {artifact.sources.map((source) => (
                    <li key={source}><code className="connections-local-code">{source}</code></li>
                  ))}
                </ol>
              )}
            </li>
          ))}
        </ul>
      )}
      {install.detail && !install.ready && (
        <pre className="connections-local-log" aria-label="Details of the last attempt" tabIndex={0}>{install.detail}</pre>
      )}
      <div className="connections-local-actions">
        {install.active ? (
          <button
            type="button"
            className="connections-row-action-button"
            disabled={disabled}
            onClick={() => onTrackRequest(requestCancelPrepareLocalServer(connectionId))}
          >
            Cancel
          </button>
        ) : null}
        {canPrepare ? (
          <button
            type="button"
            className="connections-row-action-button connections-row-action-primary"
            disabled={disabled}
            onClick={() => onTrackRequest(requestPrepareLocalServer(connectionId))}
          >
            {install.phase === 'idle' ? 'Prepare' : 'Try again'}
          </button>
        ) : null}
      </div>
    </div>
  )
}
