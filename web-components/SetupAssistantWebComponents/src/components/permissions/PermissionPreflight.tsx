import { useEffect, useMemo, useState } from 'react'

import {
  closeSetupAssistant,
  continueSetupAssistant,
  openSystemSettings,
  requestPermission,
  restartApplication,
} from '@/services/bridge'

type PermissionKind = 'microphone' | 'accessibility' | 'input_monitoring' | 'screen_recording' | 'apple_events'
type PermissionStatus = 'unknown' | 'granted' | 'denied' | 'not_determined'

type PermissionStatusMap = Record<PermissionKind, PermissionStatus>

interface PermissionStatusEventDetail {
  permissions?: Partial<PermissionStatusMap>
}

declare global {
  interface Window {
    basilSetupAssistantConfig?: {
      isReturningUserCheck?: boolean
    }
  }
}

function isReturningUserCheck() {
  return window.basilSetupAssistantConfig?.isReturningUserCheck === true
}

function MicrophoneIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3.5a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0v-5a3 3 0 0 0-3-3Z" />
      <path d="M6.75 10.75a.75.75 0 0 1 1.5 0v.75a3.75 3.75 0 0 0 7.5 0v-.75a.75.75 0 0 1 1.5 0v.75a5.25 5.25 0 0 1-4.5 5.2v2.05h2.1a.75.75 0 0 1 0 1.5h-5.7a.75.75 0 0 1 0-1.5h2.1V16.7a5.25 5.25 0 0 1-4.5-5.2v-.75Z" />
    </svg>
  )
}

function AccessibilityIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 5.2a2.1 2.1 0 1 0 0-4.2 2.1 2.1 0 0 0 0 4.2Z" />
      <path d="M4.6 7.15a.85.85 0 0 1 .96-.72c4.16.59 8.72.59 12.88 0a.85.85 0 1 1 .24 1.68c-1.78.25-3.66.4-5.53.44v3.02l2.88 7.25a.9.9 0 0 1-1.67.66L12 13.55l-2.36 5.93a.9.9 0 1 1-1.67-.66l2.88-7.25V8.55a45.2 45.2 0 0 1-5.53-.44.85.85 0 0 1-.72-.96Z" />
    </svg>
  )
}

function InputMonitoringIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 6.75A2.25 2.25 0 0 1 6.75 4.5h10.5a2.25 2.25 0 0 1 2.25 2.25v6.5a2.25 2.25 0 0 1-2.25 2.25H14.7l1.15 2h1.4a.75.75 0 0 1 0 1.5H6.75a.75.75 0 0 1 0-1.5h1.4l1.15-2H6.75a2.25 2.25 0 0 1-2.25-2.25v-6.5Zm2.25-.75a.75.75 0 0 0-.75.75v6.5c0 .41.34.75.75.75h10.5c.41 0 .75-.34.75-.75v-6.5a.75.75 0 0 0-.75-.75H6.75Z" />
      <path d="M8.1 8.4h1.5v1.5H8.1V8.4Zm3.15 0h1.5v1.5h-1.5V8.4Zm3.15 0h1.5v1.5h-1.5V8.4Zm-5.8 3.1h6.8V13h-6.8v-1.5Z" />
    </svg>
  )
}

function AutomationIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M8.1 4.2 9 2.5h2l.9 1.7 1.9.55.55 1.9 1.7.9v2l-1.7.9-.55 1.9-1.9.55-.9 1.7H9l-.9-1.7-1.9-.55-.55-1.9-1.7-.9v-2l1.7-.9.55-1.9 1.9-.55Zm1.9 6.45a2.1 2.1 0 1 0 0-4.2 2.1 2.1 0 0 0 0 4.2Z" />
      <path d="m16.1 13.25.6-1.15h1.5l.6 1.15 1.3.38.38 1.3 1.15.6v1.5l-1.15.6-.38 1.3-1.3.38-.6 1.15h-1.5l-.6-1.15-1.3-.38-.38-1.3-1.15-.6v-1.5l1.15-.6.38-1.3 1.3-.38Zm1.35 4.4a1.35 1.35 0 1 0 0-2.7 1.35 1.35 0 0 0 0 2.7Z" />
    </svg>
  )
}

function ScreenRecordingIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 5.75h15a2 2 0 0 1 2 2v7.7a2 2 0 0 1-2 2h-15a2 2 0 0 1-2-2v-7.7a2 2 0 0 1 2-2Zm0 1.5a.5.5 0 0 0-.5.5v7.7a.5.5 0 0 0 .5.5h15a.5.5 0 0 0 .5-.5v-7.7a.5.5 0 0 0-.5-.5h-15Z" />
      <path d="M7.3 4.25h2.2v1.5H7.3v-1.5Zm7.2 0h2.2v1.5h-2.2v-1.5Zm-7.2 13.2h2.2v1.5H7.3v-1.5Zm7.2 0h2.2v1.5h-2.2v-1.5ZM2.5 9.2H4v2.2H2.5V9.2Zm17.5 0h1.5v2.2H20V9.2Z" />
    </svg>
  )
}

const permissionCards = [
  {
    kind: 'microphone' as const,
    title: 'Microphone Access',
    description: 'Basil needs microphone access for audio transcription and agentTasks.',
    icon: <MicrophoneIcon />,
  },
  {
    kind: 'accessibility' as const,
    title: 'Accessibility',
    description: 'Basil needs Accessibility access to simulate keystrokes for pasting text and to understand on-screen context for some features.',
    icon: <AccessibilityIcon />,
  },
  {
    kind: 'input_monitoring' as const,
    title: 'Input Monitoring',
    description: 'Basil needs Input Monitoring so global hotkeys and double-tap modifier gestures work even when another app is focused.',
    icon: <InputMonitoringIcon />,
  },
  {
    kind: 'apple_events' as const,
    title: 'Apple Events',
    description: 'Basil needs to control other applications (like Finder or your web browser) for certain automation tasks and screen capture.',
    icon: <AutomationIcon />,
  },
  {
    kind: 'screen_recording' as const,
    title: 'Screen Recording',
    description: "Required for enhanced suggestions and OCR by capturing screen content. macOS may require an app restart after granting this permission.",
    icon: <ScreenRecordingIcon />,
  },
]

const initialPermissionStatuses: PermissionStatusMap = {
  microphone: 'unknown',
  accessibility: 'unknown',
  input_monitoring: 'unknown',
  screen_recording: 'unknown',
  apple_events: 'unknown',
}

function requestPermissionStatusRefresh() {
  window.webkit?.messageHandlers?.setupAssistant?.postMessage({
    version: 1,
    name: 'requestPermissionStatus',
  })
}

function formatPermissionStatus(status: PermissionStatus) {
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

function statusIcon(status: PermissionStatus) {
  switch (status) {
    case 'granted':
      return '●'
    case 'denied':
      return '×'
    case 'not_determined':
      return '?'
    default:
      return '○'
  }
}

function permissionStatusClass(status: PermissionStatus) {
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

function permissionNeedsRestart(kind: PermissionKind) {
  return kind === 'screen_recording' || kind === 'accessibility' || kind === 'input_monitoring'
}

export function PermissionPreflight() {
  const [permissionStatuses, setPermissionStatuses] = useState<PermissionStatusMap>(
    initialPermissionStatuses,
  )
  const [restartRecommended, setRestartRecommended] = useState(false)

  useEffect(() => {
    const handlePermissionStatus = (event: Event) => {
      const detail = (event as CustomEvent<PermissionStatusEventDetail>).detail
      if (!detail?.permissions) {
        return
      }

      setPermissionStatuses(currentStatuses => ({
        ...currentStatuses,
        ...detail.permissions,
      }))
    }

    window.addEventListener('setupAssistantPermissionStatus', handlePermissionStatus)
    requestPermissionStatusRefresh()

    return () => {
      window.removeEventListener('setupAssistantPermissionStatus', handlePermissionStatus)
    }
  }, [])

  const allPermissionsGranted = useMemo(
    () => permissionCards.every(card => permissionStatuses[card.kind] === 'granted'),
    [permissionStatuses],
  )

  const showProminentRestartCard = restartRecommended

  function markRestartRecommendedIfNeeded(kind: PermissionKind) {
    if (permissionNeedsRestart(kind)) {
      setRestartRecommended(true)
    }
  }

  function handleRequestPermission(kind: PermissionKind) {
    markRestartRecommendedIfNeeded(kind)
    requestPermission(kind)
  }

  function handleOpenSystemSettings(kind: PermissionKind) {
    markRestartRecommendedIfNeeded(kind)
    openSystemSettings(kind)
  }

  return (
    <main className="permissions-gate">
      <section className="permissions-panel">
        <header className="permissions-header">
          <div>
            <h1>{isReturningUserCheck() ? 'Welcome Back' : 'Permissions'}</h1>
            <p>
              {isReturningUserCheck()
                ? "Let's confirm your permissions are still set. If any are missing, grant them now — Basil needs them to work properly."
                : "Last step — grant these permissions and you're good to go. Basil needs them to transcribe audio, insert results, and control certain apps for automation."}
            </p>
          </div>
          <button type="button" className="secondary-button" onClick={requestPermissionStatusRefresh}>
            Refresh
          </button>
        </header>

        <div className="permission-list">
          {permissionCards.map(card => {
            const status = permissionStatuses[card.kind]
            const isGranted = status === 'granted'

            return (
              <article key={card.kind} className={`permission-row permission-${card.kind}`}>
                <div className="permission-icon" aria-hidden="true">
                  {card.icon}
                </div>

                <div className="permission-row-body">
                  <div className="permission-row-heading">
                    <h3>{card.title}</h3>
                    <span className={`permission-status ${permissionStatusClass(status)}`}>
                      <span aria-hidden="true">{statusIcon(status)}</span>
                      {formatPermissionStatus(status)}
                    </span>
                  </div>

                  <p>{card.description}</p>

                  <div className="permission-actions">
                    {!isGranted && (
                      <button type="button" className="primary-button" onClick={() => handleRequestPermission(card.kind)}>
                        {status === 'not_determined' ? 'Request Permission' : 'Request Again'}
                      </button>
                    )}
                    <button type="button" className="secondary-button" onClick={() => handleOpenSystemSettings(card.kind)}>
                      Open System Settings
                    </button>
                  </div>
                </div>
              </article>
            )
          })}
        </div>

        {showProminentRestartCard && (
          <div className="permissions-restart-card">
            <p>
              Restart Basil to finish applying permission changes. Setup will continue after
              Basil reopens and confirms these permissions are granted.
            </p>
            <button type="button" className="primary-button" onClick={restartApplication}>
              Restart Basil
            </button>
          </div>
        )}
        {allPermissionsGranted && !showProminentRestartCard && isReturningUserCheck() && (
          <div className="permissions-restart-card">
            <p>
              You&apos;re all set. Basil can now use the permissions you enabled. You can revisit
              setup any time from Settings › General › Application Setup.
            </p>
            <button type="button" className="primary-button" onClick={closeSetupAssistant}>
              Done
            </button>
          </div>
        )}
        {allPermissionsGranted && !showProminentRestartCard && !isReturningUserCheck() && (
          <div className="permissions-restart-card">
            <p>Permissions are ready. Continue when you&apos;re ready to set up Basil.</p>
            <button type="button" className="primary-button" onClick={continueSetupAssistant}>
              Continue
            </button>
          </div>
        )}
        {!allPermissionsGranted && !showProminentRestartCard && (
          <button type="button" className="secondary-button permissions-restart-secondary" onClick={restartApplication}>
            Restart Basil after updating permissions
          </button>
        )}
      </section>
    </main>
  )
}

