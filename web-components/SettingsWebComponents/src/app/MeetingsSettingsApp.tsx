import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import { AppExclusionPicker } from '../components/AppExclusionPicker'
import { MeetingAutomationPanel } from '../components/MeetingAutomationPanel'
import { PolicyRadioGroup, type PolicyRadioOption } from '../components/PolicyRadioGroup'
import { useOptimisticSettings } from './useOptimisticSettings'
import {
  notifyMeetingDetectionSettingsReady,
  onMeetingDetectionEvent,
  requestAddExcludedBundleId,
  requestMeetingDetectionAvailableApps,
  requestMeetingDetectionSearchApps,
  requestRemoveExcludedBundleId,
  requestUpdateExcludedAppNames,
  requestUpdateInactivityTimeoutMinutes,
  requestUpdateMeetingDetectionAutoEnd,
  requestUpdateMeetingDetectionCooldownMinutes,
  requestUpdateMeetingDetectionEnabled,
  requestUpdateMeetingDetectionMode,
  requestUpdateMeetingDetectionPollSeconds,
  requestUpdateRequireCalendarMatch,
  requestUpdateUseCalendarEnrichment,
} from '../services/meetingDetectionBridge'
import type { MeetingDetectionAppOption, MeetingDetectionSettingsFields } from '../types'

const MODE_OPTIONS: readonly PolicyRadioOption<'prompt' | 'auto_start'>[] = [
  { id: 'prompt', label: 'Prompt me' },
  { id: 'auto_start', label: 'Start automatically' },
]

const COOLDOWN_OPTIONS: readonly PolicyRadioOption<'5' | '10' | '30' | '60'>[] = [
  { id: '5', label: '5 Minutes' },
  { id: '10', label: '10 Minutes' },
  { id: '30', label: '30 Minutes' },
  { id: '60', label: '1 Hour' },
]

function NumericField({ id, label, suffix, value, min, max, step, disabled, onCommit }: {
  id: string
  label: string
  suffix: string
  value: number
  min: number
  max: number
  step: number
  disabled?: boolean
  onCommit: (next: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])

  function commit() {
    const parsed = Number(draft)
    const next = Number.isFinite(parsed) ? Math.min(max, Math.max(min, parsed)) : value
    setDraft(String(next))
    if (next !== value) onCommit(next)
  }

  return (
    <div className="meetings-numeric-field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }}
      />
      <span>{suffix}</span>
    </div>
  )
}

function rememberInto(
  map: Record<string, MeetingDetectionAppOption>,
  apps: MeetingDetectionAppOption[]
): Record<string, MeetingDetectionAppOption> {
  if (apps.length === 0) return map
  const next = { ...map }
  apps.forEach((app) => { next[app.bundleId] = app })
  return next
}

export function MeetingsSettingsApp() {
  const { settings, isSaving, setSettings, track, receiveSnapshot, resolveIntent } = useOptimisticSettings<MeetingDetectionSettingsFields>()
  const [requiredBundleIds, setRequiredBundleIds] = useState<string[]>([])
  const [availableApps, setAvailableApps] = useState<MeetingDetectionAppOption[]>([])
  const [searchResults, setSearchResults] = useState<MeetingDetectionAppOption[]>([])
  const [knownAppsByBundleId, setKnownAppsByBundleId] = useState<Record<string, MeetingDetectionAppOption>>({})
  const [excludedNamesDraft, setExcludedNamesDraft] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const searchRequestIdRef = useRef<string | null>(null)

  useEffect(() => {
    const unsubscribe = onMeetingDetectionEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        receiveSnapshot(event.settings)
        setRequiredBundleIds(event.requiredBundleIds)
        setKnownAppsByBundleId((prev) => rememberInto(prev, event.excludedApps))
        setLoadError(null)
        if (event.type === 'init') {
          setAvailableApps(event.availableApps)
          setKnownAppsByBundleId((prev) => rememberInto(prev, event.availableApps))
        }
        return
      }
      if (event.type === 'availableApps') {
        setAvailableApps(event.availableApps)
        setKnownAppsByBundleId((prev) => rememberInto(prev, event.availableApps))
        return
      }
      if (event.type === 'searchAppsResults') {
        if (event.requestId !== searchRequestIdRef.current) return
        setSearchResults(event.apps)
        setKnownAppsByBundleId((prev) => rememberInto(prev, event.apps))
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && resolveIntent(event.requestId, event.status) === 'error') {
        setRequestError(event.message ?? 'Failed to update setting.')
      }
    })
    notifyMeetingDetectionSettingsReady()
    return unsubscribe
  }, [])

  const excludedNamesValue = settings?.excludedAppNames.join('\n')

  useEffect(() => {
    if (excludedNamesValue !== undefined) setExcludedNamesDraft(excludedNamesValue)
  }, [excludedNamesValue])

  function submit(id: string) {
    setRequestError(null)
    track(id)
  }

  if (!settings && !loadError) {
    return <p className="meetings-settings-status" role="status">Loading Meeting/Call Detection settings...</p>
  }

  if (loadError) {
    return (
      <div className="meetings-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyMeetingDetectionSettingsReady()}>Retry</button>
      </div>
    )
  }

  const s = settings!

  return (
    <div className="meetings-settings-shell">
      <section className="meetings-settings-section" aria-labelledby="meetings-detection-heading">
        <h2 id="meetings-detection-heading">Meeting/Call Detection</h2>
        <Switch
          id="meetings-detection-enabled"
          label="Enable Meeting/Call Detection"
          checked={s.enabled}
          onChange={(checked) => { setSettings({ ...s, enabled: checked }); submit(requestUpdateMeetingDetectionEnabled(checked)) }}
        />
        <p className="meetings-settings-hint">
          When enabled, Basil watches for processes using both microphone input and audio output, then offers to start transcription. You still start the monitor manually from the menu bar.
        </p>
        <div className="meetings-detection-columns">
          <div className="meetings-detection-column">
            <PolicyRadioGroup
              legend="On detection"
              name="meeting-detection-mode"
              options={MODE_OPTIONS}
              value={s.mode}
              onChange={(next) => { setSettings({ ...s, mode: next }); submit(requestUpdateMeetingDetectionMode(next)) }}
            />
            <NumericField
              id="meetings-poll-seconds"
              label="Check Every"
              suffix="seconds"
              value={s.pollSeconds}
              min={1}
              max={600}
              step={1}
              onCommit={(next) => { setSettings({ ...s, pollSeconds: next }); submit(requestUpdateMeetingDetectionPollSeconds(next)) }}
            />
          </div>
          <div className="meetings-detection-column">
            <PolicyRadioGroup
              legend="Cooldown"
              name="meeting-detection-cooldown"
              options={COOLDOWN_OPTIONS}
              value={String(s.cooldownMinutes) as '5' | '10' | '30' | '60'}
              onChange={(next) => {
                const nextMinutes = Number(next)
                setSettings({ ...s, cooldownMinutes: nextMinutes })
                submit(requestUpdateMeetingDetectionCooldownMinutes(nextMinutes))
              }}
            />
          </div>
        </div>
      </section>

      <section className="meetings-settings-section" aria-labelledby="meetings-calendar-heading">
        <h2 id="meetings-calendar-heading">Calendar</h2>
        <Switch
          id="meetings-use-calendar-enrichment"
          label="Enrich meetings with calendar events"
          checked={s.useCalendarEnrichment}
          onChange={(checked) => { setSettings({ ...s, useCalendarEnrichment: checked }); submit(requestUpdateUseCalendarEnrichment(checked)) }}
        />
        <Switch
          id="meetings-require-calendar-match"
          label="Only detect when a calendar event is active"
          checked={s.requireCalendarMatch}
          onChange={(checked) => { setSettings({ ...s, requireCalendarMatch: checked }); submit(requestUpdateRequireCalendarMatch(checked)) }}
        />
        <p className="meetings-settings-hint">
          Requiring a calendar match reduces false positives from non-meeting audio (e.g. browser media), at the cost of missing ad-hoc calls.
        </p>
        <Switch
          id="meetings-auto-end"
          label="Offer to end recording when audio stops"
          checked={s.autoEnd}
          onChange={(checked) => { setSettings({ ...s, autoEnd: checked }); submit(requestUpdateMeetingDetectionAutoEnd(checked)) }}
        />
        <NumericField
          id="meetings-inactivity-timeout"
          label="End After"
          suffix="minutes inactive"
          value={s.inactivityTimeoutMinutes}
          min={0}
          max={120}
          step={0.5}
          disabled={!s.autoEnd}
          onCommit={(next) => { setSettings({ ...s, inactivityTimeoutMinutes: next }); submit(requestUpdateInactivityTimeoutMinutes(next)) }}
        />
      </section>

      <section className="meetings-settings-section" aria-labelledby="meetings-excluded-apps-heading">
        <h2 id="meetings-excluded-apps-heading">Excluded Apps</h2>
        <AppExclusionPicker
          selectedBundleIds={s.excludedBundleIds}
          requiredBundleIds={requiredBundleIds}
          availableApps={availableApps}
          searchResults={searchResults}
          knownAppsByBundleId={knownAppsByBundleId}
          onFocusSearch={() => requestMeetingDetectionAvailableApps()}
          onSearchQueryChange={(query) => { searchRequestIdRef.current = requestMeetingDetectionSearchApps(query) }}
          onAdd={(bundleId) => {
            setSettings({ ...s, excludedBundleIds: [...s.excludedBundleIds, bundleId] })
            submit(requestAddExcludedBundleId(bundleId))
          }}
          onRemove={(bundleId) => {
            setSettings({ ...s, excludedBundleIds: s.excludedBundleIds.filter((id) => id !== bundleId) })
            submit(requestRemoveExcludedBundleId(bundleId))
          }}
        />
        <p className="meetings-settings-hint">Choose apps Basil should never treat as meetings. Basil excludes itself automatically.</p>
      </section>

      <section className="meetings-settings-section" aria-labelledby="meetings-exclusions-heading">
        <h2 id="meetings-exclusions-heading">Exclusions</h2>
        <textarea
          className="meetings-exclusions-textarea"
          rows={4}
          value={excludedNamesDraft}
          onChange={(event) => setExcludedNamesDraft(event.target.value)}
        />
        <p className="meetings-settings-hint">Excluded app names, one per line.</p>
        <button
          type="button"
          className="secondary-button"
          onClick={() => submit(requestUpdateExcludedAppNames(excludedNamesDraft.split('\n').map((line) => line.trim()).filter((line) => line.length > 0)))}
        >
          Apply Exclusions
        </button>
      </section>

      <MeetingAutomationPanel />

      <p className="settings-visually-hidden" role="status">{isSaving ? 'Saving setting...' : ''}</p>
      {requestError && <p className="meetings-settings-inline-error" role="alert">{requestError}</p>}
    </div>
  )
}
