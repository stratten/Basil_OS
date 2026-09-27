import { useEffect, useState } from 'react'
import type { PermissionKind, PermissionStatusValue, PermissionsApplicationStatusMap } from '../types'
import {
  notifyPermissionsApplicationReady,
  onPermissionsApplicationEvent,
  openSystemSettings,
  requestPermission,
  requestPermissionStatus,
} from '../services/permissionsApplicationBridge'

function PermissionIcon({ kind }: { kind: PermissionKind }) {
  switch (kind) {
    case 'microphone':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5a3 3 0 0 0-3 3v5a3.75 3.75 0 0 0 6 0v-5a3 3 0 0 0-3-3Z" /><path d="M6.75 10.75a.75.75 0 0 1 1.5 0v.75a3.75 3.75 0 0 0 7.5 0v-.75a.75.75 0 0 1 1.5 0v.75a5.25 5.25 0 0 1-4.5 5.2v2.05h2.1a.75.75 0 0 1 0 1.5h-5.7a.75.75 0 0 1 0-1.5h2.1V16.7a5.25 5.25 0 0 1-4.5-5.2v-.75Z" /></svg>
    case 'accessibility':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5.2a2.1 2.1 0 1 0 0-4.2 2.1 2.1 0 0 0 0 4.2Z" /><path d="M4.6 7.15a.85.85 0 0 1 .96-.72c4.16.59 8.72.59 12.88 0a.85.85 0 1 1 .24 1.68c-1.78.25-3.66.4-5.53.44v3.02l2.88 7.25a.9.9 0 1 1-1.67.66L12 13.55l-2.36 5.93a.9.9 0 1 1-1.67-.66l2.88-7.25V8.55a45.2 45.2 0 0 1-5.53-.44.85.85 0 0 1-.72-.96Z" /></svg>
    case 'input_monitoring':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 6.75A2.25 2.25 0 0 1 6.75 4.5h10.5a2.25 2.25 0 0 1 2.25 2.25v6.5a2.25 2.25 0 0 1-2.25 2.25H14.7l1.15 2h1.4a.75.75 0 0 1 0 1.5H6.75a.75.75 0 0 1 0-1.5h1.4l1.15-2H6.75a2.25 2.25 0 0 1-2.25-2.25v-6.5Zm2.25-.75a.75.75 0 0 0-.75.75v6.5c0 .41.34.75.75.75h10.5c.41 0 .75-.34.75-.75v-6.5a.75.75 0 0 0-.75-.75H6.75Z" /><path d="M8.1 8.4h1.5v1.5H8.1V8.4Zm3.15 0h1.5v1.5h-1.5V8.4Zm3.15 0h1.5v1.5h-1.5V8.4Zm-5.8 3.1h6.8V13h-6.8v-1.5Z" /></svg>
    case 'apple_events':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.1 4.2 9 2.5h2l.9 1.7 1.9.55.55 1.9 1.7.9v2l-1.7.9-.55 1.9-1.9.55-.9 1.7H9l-.9-1.7-1.9-.55-.55-1.9-1.7-.9v-2l1.7-.9.55-1.9 1.9-.55Zm1.9 6.45a2.1 2.1 0 1 0 0-4.2 2.1 2.1 0 0 0 0 4.2Z" /><path d="m16.1 13.25.6-1.15h1.5l.6 1.15 1.3.38.38 1.3 1.15.6v1.5l-1.15.6-.38 1.3-1.3.38-.6 1.15h-1.5l-.6-1.15-1.3-.38-.38-1.3-1.15-.6v-1.5l1.15-.6.38-1.3 1.3-.38Zm1.35 4.4a1.35 1.35 0 1 0 0-2.7 1.35 1.35 0 0 0 0 2.7Z" /></svg>
    case 'screen_recording':
      return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 5.75h15a2 2 0 0 1 2 2v7.7a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-7.7a2 2 0 0 1 2-2Zm0 1.5a.5.5 0 0 0-.5.5v7.7a.5.5 0 0 0 .5.5h15a.5.5 0 0 0 .5-.5v-7.7a.5.5 0 0 0-.5-.5h-15Z" /><path d="M7.3 4.25h2.2v1.5H7.3v-1.5Zm7.2 0h2.2v1.5h-2.2v-1.5Zm-7.2 13.2h2.2v1.5H7.3v-1.5Zm7.2 0h2.2v1.5h-2.2v-1.5ZM2.5 9.2H4v2.2H2.5V9.2Zm17.5 0h1.5v2.2H20V9.2Z" /></svg>
  }
}

const INITIAL_STATUSES: PermissionsApplicationStatusMap = {
  microphone: 'unknown',
  accessibility: 'unknown',
  inputMonitoring: 'unknown',
  screenRecording: 'unknown',
  appleEvents: 'unknown',
}

const PERMISSION_ROWS: readonly { key: keyof PermissionsApplicationStatusMap; kind: PermissionKind; title: string; description: string }[] = [
  { key: 'microphone', kind: 'microphone', title: 'Microphone Access', description: 'Basil needs microphone access for audio transcription and agent tasks.' },
  { key: 'accessibility', kind: 'accessibility', title: 'Accessibility', description: 'Basil needs Accessibility access to simulate keystrokes for pasting text and to understand on-screen context for some features.' },
  { key: 'inputMonitoring', kind: 'input_monitoring', title: 'Input Monitoring', description: 'Basil needs Input Monitoring so global hotkeys and double-tap modifier gestures work even when another app is focused.' },
  { key: 'appleEvents', kind: 'apple_events', title: 'Apple Events', description: 'Basil needs to control other applications for certain automation tasks and screen capture.' },
  { key: 'screenRecording', kind: 'screen_recording', title: 'Screen Recording', description: 'Required for enhanced suggestions and OCR by capturing screen content. macOS may require an app restart after granting this permission.' },
]

function statusLabel(status: PermissionStatusValue): string {
  switch (status) {
    case 'granted':
      return 'Granted'
    case 'denied':
      return 'Denied'
    case 'not_determined':
      return 'Not Yet Requested'
    default:
      return 'Unknown'
  }
}

function statusClass(status: PermissionStatusValue): string {
  switch (status) {
    case 'granted':
      return 'granted'
    case 'denied':
      return 'denied'
    case 'not_determined':
      return 'not-determined'
    default:
      return 'unknown'
  }
}

function statusIcon(status: PermissionStatusValue): string {
  switch (status) {
    case 'granted': return '●'
    case 'denied': return '×'
    case 'not_determined': return '?'
    default: return '○'
  }
}

export function PermissionsApplicationPanel() {
  const [permissions, setPermissions] = useState<PermissionsApplicationStatusMap>(INITIAL_STATUSES)

  useEffect(() => {
    const unsubscribe = onPermissionsApplicationEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setPermissions(event.permissions)
      }
    })
    notifyPermissionsApplicationReady()
    requestPermissionStatus()
    return unsubscribe
  }, [])

  return (
    <section className="permissions-application-panel">
      <header className="permissions-application-header">
        <div>
          <h2>Application Permissions</h2>
          <p>Grant these permissions to let Basil transcribe audio, insert results, and control certain apps for automation.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => requestPermissionStatus()}>
          Refresh
        </button>
      </header>

      <div className="permission-list">
        {PERMISSION_ROWS.map((row) => {
          const status = permissions[row.key]
          const isGranted = status === 'granted'
          return (
            <article key={row.key} className={`permission-row permission-${row.kind}`}>
              <div className="permission-icon">
                <PermissionIcon kind={row.kind} />
              </div>
              <div className="permission-row-body">
                <div className="permission-row-heading">
                  <h3>{row.title}</h3>
                  <span className={`permission-status ${statusClass(status)}`}>
                    <span aria-hidden="true">{statusIcon(status)}</span>
                    {statusLabel(status)}
                  </span>
                </div>
                <p>{row.description}</p>
              </div>
              <div className="permission-actions">
                {!isGranted && (
                  <button type="button" className="primary-button" onClick={() => requestPermission(row.kind)}>
                    {status === 'not_determined' ? 'Request Permission' : 'Request Again'}
                  </button>
                )}
                <button type="button" className="secondary-button" onClick={() => openSystemSettings(row.kind)}>
                  Open System Settings
                </button>
              </div>
            </article>
          )
        })}
      </div>
    </section>
  )
}
