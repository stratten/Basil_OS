import type { ModelRowSnapshot } from '../types'
import { displayInfoForModel, formatBytes } from '../helpers/modelDisplay'

interface Props {
  row: ModelRowSnapshot
  isActionPending: boolean
  onRetry: (modelId: string) => void
  onCancel: (modelId: string) => void
}

function StatusIcon({ status, isRetrying }: Pick<ModelRowSnapshot, 'status' | 'isRetrying'>) {
  if (isRetrying) return <span className="model-row-icon model-row-icon--retrying" aria-label="Starting download">↻</span>
  if (status === 'completed' || status === 'skipped_installed') return <span className="model-row-icon model-row-icon--completed" aria-label="Downloaded">✓</span>
  if (status === 'queued' || status === 'downloading') return <span className="model-row-icon model-row-icon--active" aria-label={status === 'queued' ? 'Queued' : 'Downloading'}>↓</span>
  return <span className="model-row-icon model-row-icon--stalled" aria-label="Download needs attention">◌</span>
}

export default function ModelRow({ row, isActionPending, onRetry, onCancel }: Props) {
  const { title, technicalName } = displayInfoForModel(row.modelId)
  const isQueued = row.status === 'queued'
  const isDownloading = row.status === 'downloading'
  const isActive = isQueued || isDownloading
  const isDone = row.status === 'completed' || row.status === 'skipped_installed'
  const isRetryable = row.status === 'failed' || row.status === 'user_cancelled'
  const actionIsPending = isActionPending || row.isRetrying

  return (
    <div className="model-row">
      <div className="model-row-summary">
        <StatusIcon status={row.status} isRetrying={actionIsPending} />
        <div className="model-row-labels">
          <span className="model-row-title" title={title}>{title}</span>
          <span className="model-row-technical" title={technicalName}>{technicalName}</span>
        </div>
        <div className="model-row-action">
          {isDone && <span className="model-row-done">Done</span>}
          {!isDone && actionIsPending && <span className="model-row-pending">Starting...</span>}
          {!isDone && !actionIsPending && isRetryable && (
            <button type="button" onClick={() => onRetry(row.modelId)} aria-label={`Retry ${title}`}>
              Retry
            </button>
          )}
          {!isDone && !actionIsPending && isQueued && <span className="model-row-pending">Queued</span>}
          {!isDone && !actionIsPending && isDownloading && (
            <>
              <span className="model-row-percent">{Math.trunc(row.progress)}%</span>
              <button type="button" className="model-row-stop" onClick={() => onCancel(row.modelId)} aria-label={`Stop ${title} download`}>
                ■
              </button>
            </>
          )}
        </div>
      </div>
      {!isDone && isActive && (
        <div className="model-row-progress">
          <span className="model-row-progress-fill model-row-progress-fill--active" style={{ width: `${Math.max(0, Math.min(100, row.progress))}%` }} />
        </div>
      )}
      {!isDone && isActive && row.totalDownloaded != null && row.totalSize != null && row.totalSize > 0 && (
        <span className="model-row-bytes">{formatBytes(row.totalDownloaded)} / {formatBytes(row.totalSize)}</span>
      )}
    </div>
  )
}
