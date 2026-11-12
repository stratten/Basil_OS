import { DownloadProgress } from '@shared/DownloadProgress'

import { startableRows, type StarterDownloadRow, type StarterDownloadState } from './starterDownloads'

export type ModelStartMethod = 'download' | 'copy'

const STATE_LABELS: Record<StarterDownloadState, string> = {
  pending: 'Not downloaded',
  downloading: 'Downloading',
  completed: 'Ready',
  failed: 'Failed',
}

interface Props {
  rows: StarterDownloadRow[]
  /** Row ids whose start request is in flight, so their buttons wait instead of starting twice. */
  startingIds: ReadonlySet<string>
  error: string | null
  onStart: (row: StarterDownloadRow, method: ModelStartMethod) => void
  onStartAll: (method: ModelStartMethod) => void
}

/**
 * One row per model with its real name, what it is for, its size and its state, and a compact button on the right to start it.
 * "Download all" sits right below the list. A validation build also offers "Copy from my Basil", which copies an installed model from the normal app instead of downloading it.
 */
export function ModelDownloadRows({ rows, startingIds, error, onStart, onStartAll }: Props) {
  const startable = startableRows(rows)
  const copyable = startable.filter(row => row.canCopy)
  const isAnyStarting = startingIds.size > 0

  return (
    <div className="model-downloads">
      <ul className="model-downloads__list">
        {rows.map(row => {
          const isStarting = startingIds.has(row.id)
          const canStart = row.state === 'pending' || row.state === 'failed'
          return (
            <li key={row.id} className={`model-downloads__row model-downloads__row--${row.state}`}>
              <div className="model-downloads__identity">
                <span className="model-downloads__name">{row.title}</span>
                <span className="model-downloads__role">{row.role}</span>
                {row.detail && <span className="model-downloads__detail">{row.detail}</span>}
              </div>
              <div className="model-downloads__action">
                {canStart ? (
                  <>
                    {row.state === 'failed' && <span className="model-downloads__state">{STATE_LABELS.failed}</span>}
                    <button
                      type="button"
                      className="secondary-button model-downloads__button"
                      disabled={isStarting}
                      aria-label={`${row.state === 'failed' ? 'Retry' : 'Download'} ${row.title}`}
                      onClick={() => onStart(row, 'download')}
                    >
                      {isStarting ? 'Starting…' : row.state === 'failed' ? 'Retry' : 'Download'}
                    </button>
                    {row.canCopy && (
                      <button
                        type="button"
                        className="secondary-button model-downloads__button"
                        disabled={isStarting}
                        aria-label={`Copy ${row.title} from my normal Basil`}
                        onClick={() => onStart(row, 'copy')}
                      >
                        Copy from my Basil
                      </button>
                    )}
                  </>
                ) : row.state === 'downloading' ? null : (
                  <span className="model-downloads__state">{STATE_LABELS[row.state]}</span>
                )}
              </div>
              {row.state === 'downloading' && (
                <div className="model-downloads__progress">
                  <DownloadProgress
                    label={row.title}
                    percent={row.percent}
                    downloadedBytes={row.downloadedBytes}
                    totalBytes={row.totalBytes}
                    waitingNote={row.waitingNote}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {error && <p className="model-downloads__error" role="alert">{error}</p>}
      {(startable.length > 1 || copyable.length > 1) && (
        <div className="model-downloads__all">
          {startable.length > 1 && (
            <button
              type="button"
              className="primary-button model-downloads__button"
              disabled={isAnyStarting}
              onClick={() => onStartAll('download')}
            >
              {isAnyStarting ? 'Starting…' : 'Download all'}
            </button>
          )}
          {copyable.length > 1 && (
            <button
              type="button"
              className="secondary-button model-downloads__button"
              disabled={isAnyStarting}
              onClick={() => onStartAll('copy')}
            >
              Copy all from my Basil
            </button>
          )}
        </div>
      )}
    </div>
  )
}
