import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import { PolicyRadioGroup, type PolicyRadioOption } from '../components/PolicyRadioGroup'
import { useOptimisticSettings } from './useOptimisticSettings'
import {
  notifyBrowserAutomationSettingsReady,
  onBrowserAutomationEvent,
  requestClearAutomationBrowserProfile,
  requestRemoveRememberedDomain,
  requestUpdateAllowVisualFallback,
  requestUpdateDefaultSessionMode,
  requestUpdateForegroundControlPolicy,
  requestUpdatePreferredUserBrowser,
  requestUpdateRecordBrowserActionTrace,
  requestUpdateSensitiveFillPolicy,
  requestUpdateShowActionHighlights,
} from '../services/browserAutomationBridge'
import type {
  BrowserAutomationSessionMode,
  BrowserAutomationSettingsSnapshot,
  BrowserForegroundControlPolicy,
  BrowserPreferredUserBrowser,
  BrowserSensitiveFillPolicy,
} from '../types'

const PREFERRED_BROWSER_OPTIONS: readonly PolicyRadioOption<BrowserPreferredUserBrowser>[] = [
  { id: 'system_default', label: 'System default', description: 'Use the macOS default browser when Basil needs a user-browser automation session.' },
  { id: 'chrome', label: 'Chrome', description: 'Prefer Google Chrome for Basil user-browser automation.' },
  { id: 'edge', label: 'Edge', description: 'Prefer Microsoft Edge for Basil user-browser automation.' },
  { id: 'safari', label: 'Safari', description: 'Prefer Safari for Basil user-browser automation.' },
]

const SESSION_MODE_OPTIONS: readonly PolicyRadioOption<BrowserAutomationSessionMode>[] = [
  { id: 'user_browser', label: 'Existing browser session', description: "Use Safari, Chrome, or Edge and the user's current logged-in browser session." },
  { id: 'basil_automation_browser', label: 'Basil Automation Browser', description: 'Use the future Basil-owned background browser profile when available.' },
]

const FOREGROUND_CONTROL_OPTIONS: readonly PolicyRadioOption<BrowserForegroundControlPolicy>[] = [
  { id: 'background_only', label: 'Background / DOM only', description: 'Basil will stop and ask you to fix permissions instead of using keyboard or mouse control.' },
  { id: 'ask_before_foreground', label: 'Ask before foreground takeover', description: 'Basil may use DOM automation freely, but asks before taking over the visible browser.' },
  { id: 'allow_foreground_when_needed', label: 'Allow foreground takeover when needed', description: 'Basil may activate the browser and use keyboard or mouse automation when needed.' },
]

const SENSITIVE_FILL_OPTIONS: readonly PolicyRadioOption<BrowserSensitiveFillPolicy>[] = [
  { id: 'never', label: 'Never fill sensitive fields', description: 'Basil never fills passwords or other sensitive fields; it stops and leaves them for you.' },
  { id: 'ask_every_time', label: 'Ask every time', description: 'Basil asks for your approval each time it needs to fill a sensitive field.' },
  { id: 'approved_domains', label: 'Allow for approved domains', description: 'Basil fills sensitive fields without asking on the remembered domains below, and asks everywhere else.' },
]

export function BrowserAutomationSettingsApp() {
  const { settings, isSaving, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<BrowserAutomationSettingsSnapshot>()
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)

  useEffect(() => {
    const unsubscribe = onBrowserAutomationEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        receiveSnapshot(event.settings)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && resolveIntent(event.requestId, event.status) === 'error') {
        setRequestError(event.message ?? 'Failed to update the setting.')
      }
    })
    notifyBrowserAutomationSettingsReady()
    return unsubscribe
  }, [])

  function submit(id: string) {
    setRequestError(null)
    track(id)
  }

  if (!settings && !loadError) {
    return <p className="browser-automation-status" role="status">Loading Browser Automation settings...</p>
  }

  if (loadError) {
    return (
      <div className="browser-automation-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyBrowserAutomationSettingsReady()}>Retry</button>
      </div>
    )
  }

  const s = settings!

  return (
    <div className="browser-automation-shell">
      <section className="browser-automation-section" aria-labelledby="browser-automation-heading">
        <h2 id="browser-automation-heading">Browser Automation</h2>
        <p className="browser-automation-intro">
          Control how Basil uses browser sessions for agent tasks, including preferred browser, dedicated-session behavior, action previews, sensitive browser fields, and foreground control.
        </p>

        <div className="browser-automation-guidance">
          <h3>Browser Permission Setup</h3>
          <p>DOM-based browser automation needs macOS Automation permission plus each browser's JavaScript-from-Apple-Events setting. When those are missing, Basil should ask you to fix setup instead of guessing with keyboard or mouse clicks.</p>
          <ul>
            <li>Safari: Develop menu {'>'} Allow JavaScript from Apple Events</li>
            <li>Chrome: View {'>'} Developer {'>'} Allow JavaScript from Apple Events</li>
            <li>Edge: View {'>'} Developer {'>'} Allow JavaScript from Apple Events</li>
          </ul>
        </div>

      </section>

      <section className="browser-automation-section" aria-labelledby="browser-automation-sessions-heading">
        <h2 id="browser-automation-sessions-heading">Browser Sessions</h2>
        <div className="browser-automation-columns">
          <div className="browser-automation-column">
            <PolicyRadioGroup
              legend="Preferred User Browser"
              name="preferred-user-browser"
              options={PREFERRED_BROWSER_OPTIONS}
              value={s.preferredUserBrowser}
              onChange={(next) => { setSettings({ ...s, preferredUserBrowser: next }); submit(requestUpdatePreferredUserBrowser(next)) }}
            />
          </div>
          <div className="browser-automation-column">
            <PolicyRadioGroup
              legend="Default Browser Session"
              name="default-session-mode"
              options={SESSION_MODE_OPTIONS}
              value={s.defaultSessionMode}
              onChange={(next) => { setSettings({ ...s, defaultSessionMode: next }); submit(requestUpdateDefaultSessionMode(next)) }}
            />
            <div className="browser-automation-subgroup">
              <h3>Basil Automation Browser Profile</h3>
              <p className="browser-automation-field-hint">Clears only Basil's app-owned automation browser profile. This does not clear Safari, Chrome, or Edge data.</p>
              <button
                type="button"
                className="secondary-button"
                onClick={() => submit(requestClearAutomationBrowserProfile())}
              >
                Clear Basil Automation Browser Profile
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="browser-automation-section" aria-labelledby="browser-automation-safety-heading">
        <h2 id="browser-automation-safety-heading">Control & Safety</h2>
        <div className="browser-automation-columns">
          <div className="browser-automation-column">
            <PolicyRadioGroup
              legend="Foreground Browser Control"
              name="foreground-control-policy"
              options={FOREGROUND_CONTROL_OPTIONS}
              value={s.foregroundControlPolicy}
              onChange={(next) => { setSettings({ ...s, foregroundControlPolicy: next }); submit(requestUpdateForegroundControlPolicy(next)) }}
            />
          </div>
          <div className="browser-automation-column">
            <PolicyRadioGroup
              legend="Sensitive Fill Policy"
              name="sensitive-fill-policy"
              options={SENSITIVE_FILL_OPTIONS}
              value={s.sensitiveFillPolicy}
              onChange={(next) => { setSettings({ ...s, sensitiveFillPolicy: next }); submit(requestUpdateSensitiveFillPolicy(next)) }}
            />
            <div className="browser-automation-subgroup">
              <h3>Remembered Sensitive-Fill Domains</h3>
              {s.approvedSensitiveFillDomains.length === 0 ? (
                <p className="browser-automation-field-hint">No domains have been approved for sensitive browser fills.</p>
              ) : (
                <ul className="browser-automation-domain-list">
                  {s.approvedSensitiveFillDomains.map((approval) => (
                    <li key={approval.domain} className="browser-automation-domain-row">
                      <div className="browser-automation-domain-text">
                        <span className="browser-automation-domain-name">{approval.domain}</span>
                        <span className="browser-automation-domain-usage">Used {approval.useCount} time{approval.useCount === 1 ? '' : 's'}</span>
                      </div>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setSettings({ ...s, approvedSensitiveFillDomains: s.approvedSensitiveFillDomains.filter((item) => item.domain !== approval.domain) })
                          submit(requestRemoveRememberedDomain(approval.domain))
                        }}
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="browser-automation-section" aria-labelledby="browser-automation-feedback-heading">
        <h2 id="browser-automation-feedback-heading">Action Feedback & Fallback</h2>
        <div className="browser-automation-toggles">
          <Switch
            id="browser-automation-show-highlights"
            label="Show browser action highlights"
            checked={s.showActionHighlights}
            onChange={(checked) => { setSettings({ ...s, showActionHighlights: checked }); submit(requestUpdateShowActionHighlights(checked)) }}
          />
          <Switch
            id="browser-automation-record-trace"
            label="Record browser action trace"
            checked={s.recordBrowserActionTrace}
            onChange={(checked) => { setSettings({ ...s, recordBrowserActionTrace: checked }); submit(requestUpdateRecordBrowserActionTrace(checked)) }}
          />
          <Switch
            id="browser-automation-visual-fallback"
            label="Allow screenshot and vision fallback"
            checked={s.allowVisualFallback}
            onChange={(checked) => { setSettings({ ...s, allowVisualFallback: checked }); submit(requestUpdateAllowVisualFallback(checked)) }}
          />
        </div>
      </section>

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting...' : ''}</p>
      {requestError && <p className="browser-automation-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
