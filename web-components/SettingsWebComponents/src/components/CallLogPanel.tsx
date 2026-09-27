import { requestRefreshCallLog } from '../services/connectionsBridge'
import type { MCPCallLogEntry } from '../types'

interface CallLogPanelProps {
  entries: MCPCallLogEntry[]
  isLoading: boolean
  pendingId: string | null
  onTrackRequest: (id: string) => void
}

function statusLabel(entry: MCPCallLogEntry): string {
  switch (entry.resultClassification) {
    case 'success':
      return 'Success'
    case 'denied':
      return 'Denied'
    case 'skipped':
      return 'Skipped'
    case 'error':
      return entry.errorKind ?? 'Error'
    default:
      return entry.resultClassification
  }
}

function statusClassName(entry: MCPCallLogEntry): string {
  if (entry.resultClassification === 'success') return 'connections-call-log-status connections-call-log-status-success'
  if (entry.resultClassification === 'denied' || entry.resultClassification === 'skipped') {
    return 'connections-call-log-status connections-call-log-status-warning'
  }
  return 'connections-call-log-status connections-call-log-status-error'
}

export function CallLogPanel({ entries, isLoading, pendingId, onTrackRequest }: CallLogPanelProps) {
  const disabled = pendingId !== null

  return (
    <section className="connections-call-log" aria-labelledby="connections-call-log-heading">
      <div className="connections-call-log-header">
        <h3 id="connections-call-log-heading">Recent Activity</h3>
        <button
          type="button"
          className="secondary-button"
          disabled={disabled}
          onClick={() => onTrackRequest(requestRefreshCallLog())}
        >
          Refresh
        </button>
      </div>

      {isLoading ? (
        <p className="connections-call-log-status-message" role="status">Loading recent activity...</p>
      ) : entries.length === 0 ? (
        <p className="connections-call-log-empty">No external MCP calls have been made yet.</p>
      ) : (
        <ul className="connections-call-log-list">
          {entries.map((entry) => (
            <li key={entry.id} className="connections-call-log-row">
              <span className="connections-call-log-dot" data-status={entry.resultClassification} />
              <div className="connections-call-log-body">
                <span className="connections-call-log-tool-name">{entry.toolName}</span>
                {entry.contentPreview ? (
                  <span className="connections-call-log-preview">{entry.contentPreview}</span>
                ) : entry.errorMessage ? (
                  <span className="connections-call-log-error-message">{entry.errorMessage}</span>
                ) : null}
              </div>
              <div className="connections-call-log-meta">
                <span className={statusClassName(entry)}>{statusLabel(entry)}</span>
                <span className="connections-call-log-timestamp">{entry.startedAt}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
