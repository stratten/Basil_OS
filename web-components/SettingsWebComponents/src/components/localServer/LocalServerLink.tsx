import type { CompanionHealth } from '../../types'
import { LinkQrCode } from './LinkQrCode'

interface LocalServerLinkProps {
  health: CompanionHealth
  /** The current time in milliseconds, passed in so a test can fix it. */
  now: number
}

export function healthLabel(health: CompanionHealth): string {
  switch (health.phase) {
    case 'ready':
      return 'Linked and ready'
    case 'needs_action':
      return 'Waiting for you'
    case 'failed':
      return 'Problem'
    default:
      return 'Starting...'
  }
}

function tone(health: CompanionHealth): 'ok' | 'error' | 'neutral' {
  if (health.phase === 'ready') return 'ok'
  if (health.phase === 'failed') return 'error'
  return 'neutral'
}

/** True when the code's own expiry time has passed. A missing or unreadable expiry never hides a code. */
export function codeHasExpired(health: CompanionHealth, now: number): boolean {
  if (!health.actionExpiresAt) return false
  const expires = Date.parse(health.actionExpiresAt)
  return Number.isFinite(expires) && expires <= now
}

/** The background program's own report of whether it is linked, and the code to scan when it is waiting for one. The code is drawn here from text the backend holds in memory, and is not stored. */
export function LocalServerLink({ health, now }: LocalServerLinkProps) {
  const showCode = health.phase === 'needs_action' && health.actionKind === 'qr' && !!health.actionValue
  const expired = showCode && codeHasExpired(health, now)
  return (
    <div className="connections-local-link" role="group" aria-label="Link">
      <p className="connections-local-line">
        <span className="connections-local-label">Link</span>
        <span className={`connections-local-status connections-local-status-${tone(health)}`}>{healthLabel(health)}</span>
      </p>
      {health.message && (
        <p className={health.phase === 'failed' ? 'connections-local-error' : 'connections-local-text'} role={health.phase === 'failed' ? 'alert' : 'status'}>
          {health.message}
        </p>
      )}
      {showCode && !expired && (
        <div className="connections-local-qr-frame">
          <LinkQrCode value={health.actionValue ?? ''} label="Code to scan with your phone to link this server" />
          <p className="connections-local-text">Scan this code with your phone, following the instructions above.</p>
        </div>
      )}
      {expired && (
        <p className="connections-local-hint">This code has expired. A new one appears here when the program makes it.</p>
      )}
    </div>
  )
}
