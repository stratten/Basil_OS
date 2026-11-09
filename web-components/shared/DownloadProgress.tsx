import './download-progress.css'
import { formatBytes } from './formatBytes'

export interface DownloadProgressProps {
  /** How far along the download is, from 0 to 100. Values outside that range are clamped. */
  percent: number
  /** Bytes received so far. The amount is shown only when this and `totalBytes` are both known. */
  downloadedBytes?: number | null
  /** Bytes in the whole download. */
  totalBytes?: number | null
  /** What the progress bar is for, read out by screen readers, such as the model's name. */
  label: string
  className?: string
}

function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, Number.isFinite(value) ? value : 0))
}

/** The whole percent for display. It rounds down, so a download is never shown as finished before it is, and the small epsilon keeps 0.29 * 100 from reading as 28. */
export function wholePercent(value: number): number {
  return Math.floor(clampPercent(value) + 1e-9)
}

/**
 * The one download progress display used by the mini widget, the Setup Assistant and Settings: a slim track, then a single row with the amount downloaded on the left and the percentage on the right.
 * A surface that needs it smaller sets the --download-progress-* custom properties described in download-progress.css on a parent element, so it never needs its own copy of the markup or the styling.
 */
export function DownloadProgress({ percent, downloadedBytes, totalBytes, label, className }: DownloadProgressProps) {
  const clamped = clampPercent(percent)
  const hasAmount = typeof downloadedBytes === 'number' && downloadedBytes >= 0 && typeof totalBytes === 'number' && totalBytes > 0

  return (
    <div className={className ? `download-progress ${className}` : 'download-progress'}>
      <div
        className="download-progress__track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={wholePercent(clamped)}
      >
        <span className="download-progress__fill" style={{ width: `${clamped}%` }} />
      </div>
      <div className="download-progress__data">
        {hasAmount && <span className="download-progress__amount">{formatBytes(downloadedBytes)} / {formatBytes(totalBytes)}</span>}
        <span className="download-progress__percent">{wholePercent(clamped)}%</span>
      </div>
    </div>
  )
}
