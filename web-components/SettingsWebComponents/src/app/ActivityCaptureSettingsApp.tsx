import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  notifyActivityCaptureSettingsReady,
  onActivityCaptureEvent,
  requestActivityCaptureAvailableApps,
  requestActivityCaptureCancelProcessing,
  requestActivityCaptureClearAllCaptures,
  requestActivityCaptureClearBacklog,
  requestActivityCaptureProcessBacklog,
  requestActivityCaptureProcessingProgress,
  requestActivityCaptureSearchApps,
  requestActivityCaptureStatus,
  requestActivityCaptureTestCapture,
  requestAddActivityCaptureExcludedBundleId,
  requestRemoveActivityCaptureExcludedBundleId,
  requestUpdateActivityCaptureAutoCleanupEnabled,
  requestUpdateActivityCaptureCleanupTime,
  requestUpdateActivityCaptureEnabled,
  requestUpdateActivityCaptureFrequencySeconds,
  requestUpdateActivityCaptureIdleThresholdSeconds,
  requestUpdateActivityCaptureMaxStorageMb,
  requestUpdateActivityCapturePostWakeGraceSeconds,
  requestUpdateActivityCaptureProcessingMaxRecords,
  requestUpdateActivityCaptureProcessingMode,
  requestUpdateActivityCaptureProcessingModel,
  requestUpdateActivityCaptureRetentionDays,
  requestUpdateActivityCaptureScheduledProcessingTime,
} from '../services/activityCaptureBridge'
import type {
  ActivityCaptureAppOption,
  ActivityCaptureModelOption,
  ActivityCaptureProcessingProgress,
  ActivityCaptureSettingsFields,
  ActivityCaptureStatsFields,
  ActivityCaptureStatusFields,
} from '../types'

const FREQUENCY_OPTIONS: readonly { seconds: 30 | 60 | 120 | 300 | 600; label: string }[] = [
  { seconds: 30, label: '30 Seconds' },
  { seconds: 60, label: '1 Minute' },
  { seconds: 120, label: '2 Minutes' },
  { seconds: 300, label: '5 Minutes' },
  { seconds: 600, label: '10 Minutes' },
]

function retentionLabel(days: number): string {
  return days === 0 ? 'Indefinitely' : `${days} days`
}

function progressLine(progress: ActivityCaptureProcessingProgress): string {
  const parts = [`${progress.processed} of ${progress.total} processed`]
  if (progress.succeeded > 0) parts.push(`${progress.succeeded} succeeded`)
  if (progress.failed > 0) parts.push(`${progress.failed} failed`)
  parts.push(`${progress.remaining} remaining`)
  if (progress.cancelRequested) {
    parts.push('Stopping after this capture')
  } else if (progress.etaSeconds && progress.etaSeconds > 0) {
    const minutes = Math.ceil(progress.etaSeconds / 60)
    parts.push(minutes <= 1 ? '~1 min left' : `~${minutes} min left`)
  }
  if (progress.processingStrategy === 'api_parallel') {
    parts.push(`API parallel · up to ${progress.analysisConcurrency ?? 1} concurrent analyses`)
  }
  return parts.join(' · ')
}

interface PendingActionIds {
  testCapture?: string
  processBacklog?: string
  cancelProcessing?: string
  clearBacklog?: string
  clearAllCaptures?: string
}

export function ActivityCaptureSettingsApp() {
  const [settings, setSettings] = useState<ActivityCaptureSettingsFields | null>(null)
  const [status, setStatus] = useState<ActivityCaptureStatusFields | null>(null)
  const [stats, setStats] = useState<ActivityCaptureStatsFields | null>(null)
  const [processingProgress, setProcessingProgress] = useState<ActivityCaptureProcessingProgress | null>(null)
  const [availableModels, setAvailableModels] = useState<ActivityCaptureModelOption[]>([])
  const [availableApps, setAvailableApps] = useState<ActivityCaptureAppOption[]>([])
  const [exclusionSearchResults, setExclusionSearchResults] = useState<ActivityCaptureAppOption[]>([])
  const [knownAppsByBundleId, setKnownAppsByBundleId] = useState<Record<string, ActivityCaptureAppOption>>({})
  const [retentionDayOptions, setRetentionDayOptions] = useState<number[]>([0, 7, 14, 30, 60, 90, 180, 365])
  const [maxStorageOptions, setMaxStorageOptions] = useState<number[]>([50, 100, 200, 500, 1000, 2000, 5000])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [exclusionSearchText, setExclusionSearchText] = useState('')
  const [isExclusionSearchFocused, setIsExclusionSearchFocused] = useState(false)
  const [itemsPerRunText, setItemsPerRunText] = useState('')
  const [isTestCapturing, setIsTestCapturing] = useState(false)
  const [isProcessingBacklog, setIsProcessingBacklog] = useState(false)
  const [isCancelling, setIsCancelling] = useState(false)
  const [isClearingBacklog, setIsClearingBacklog] = useState(false)
  const [isClearingAll, setIsClearingAll] = useState(false)
  const requestIdsRef = useRef<PendingActionIds>({})
  const sawActiveRef = useRef(false)
  const pollsBeforeStartRef = useRef(0)
  const progressPollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const statusIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const exclusionSearchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const exclusionSearchRequestIdRef = useRef<string | null>(null)

  function startProgressPolling() {
    sawActiveRef.current = false
    pollsBeforeStartRef.current = 0
    pollProgressOnce()
  }

  function pollProgressOnce() {
    requestActivityCaptureProcessingProgress()
    progressPollTimeoutRef.current = setTimeout(pollProgressOnce, 1200)
  }

  function stopProgressPolling() {
    if (progressPollTimeoutRef.current) clearTimeout(progressPollTimeoutRef.current)
    progressPollTimeoutRef.current = null
  }

  function rememberApps(apps: ActivityCaptureAppOption[]) {
    if (apps.length === 0) return
    setKnownAppsByBundleId((current) => {
      const next = { ...current }
      for (const app of apps) next[app.bundleId] = app
      return next
    })
  }

  function showStatus(message: string) {
    setStatusMessage(message)
    setTimeout(() => setStatusMessage((current) => (current === message ? null : current)), 5000)
  }

  useEffect(() => {
    const unsubscribe = onActivityCaptureEvent((event) => {
      if (event.type === 'init') {
        setSettings(event.settings)
        setStatus(event.status)
        setStats(event.stats)
        setProcessingProgress(event.processingProgress)
        setAvailableModels(event.availableModels)
        setAvailableApps(event.availableApps)
        rememberApps(event.availableApps)
        rememberApps(event.excludedApps)
        setRetentionDayOptions(event.retentionDayOptions)
        setMaxStorageOptions(event.maxStorageOptions)
        setItemsPerRunText(event.settings.processingMaxRecords === 0 ? '' : String(event.settings.processingMaxRecords))
        setLoadError(null)
        if (event.processingProgress?.active) {
          setIsProcessingBacklog(true)
          startProgressPolling()
        }
      } else if (event.type === 'snapshot') {
        setSettings(event.settings)
        setStats(event.stats)
        setAvailableModels(event.availableModels)
        rememberApps(event.excludedApps)
      } else if (event.type === 'status') {
        setStatus(event.status)
      } else if (event.type === 'availableApps') {
        setAvailableApps(event.availableApps)
        rememberApps(event.availableApps)
      } else if (event.type === 'searchAppsResults') {
        if (event.requestId === exclusionSearchRequestIdRef.current) {
          setExclusionSearchResults(event.apps)
          rememberApps(event.apps)
        }
      } else if (event.type === 'progress') {
        setProcessingProgress(event.processingProgress)
        if (event.processingProgress?.active) {
          sawActiveRef.current = true
        } else if (sawActiveRef.current) {
          stopProgressPolling()
          setIsProcessingBacklog(false)
          setIsCancelling(false)
          requestActivityCaptureStatus()
        } else {
          pollsBeforeStartRef.current += 1
          if (pollsBeforeStartRef.current > 5) {
            stopProgressPolling()
            setIsProcessingBacklog(false)
            setIsCancelling(false)
          }
        }
      } else if (event.type === 'intentResult') {
        const ids = requestIdsRef.current
        if (event.requestId === ids.testCapture) {
          setIsTestCapturing(false)
          if (event.message) showStatus(event.message)
        } else if (event.requestId === ids.processBacklog) {
          if (event.status === 'error') {
            setIsProcessingBacklog(false)
            if (event.message) showStatus(event.message)
          } else {
            startProgressPolling()
          }
        } else if (event.requestId === ids.cancelProcessing) {
          if (event.status === 'error') {
            setIsCancelling(false)
            if (event.message) showStatus(event.message)
          }
        } else if (event.requestId === ids.clearBacklog) {
          setIsClearingBacklog(false)
          if (event.status !== 'cancelled') {
            if (event.message) showStatus(event.message)
            requestActivityCaptureStatus()
          }
        } else if (event.requestId === ids.clearAllCaptures) {
          setIsClearingAll(false)
          if (event.status !== 'cancelled') {
            if (event.message) showStatus(event.message)
            requestActivityCaptureStatus()
          }
        } else if (event.status === 'error' && event.message) {
          showStatus(event.message)
        }
      } else if (event.type === 'loadError') {
        setLoadError(event.message)
      }
    })
    notifyActivityCaptureSettingsReady()
    statusIntervalRef.current = setInterval(() => requestActivityCaptureStatus(), 30000)
    return () => {
      unsubscribe()
      stopProgressPolling()
      if (statusIntervalRef.current) clearInterval(statusIntervalRef.current)
      if (exclusionSearchDebounceRef.current) clearTimeout(exclusionSearchDebounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function handleExclusionSearchChange(value: string) {
    setExclusionSearchText(value)
    if (exclusionSearchDebounceRef.current) clearTimeout(exclusionSearchDebounceRef.current)
    const trimmed = value.trim()
    if (trimmed.length === 0) {
      exclusionSearchRequestIdRef.current = null
      setExclusionSearchResults([])
      return
    }
    exclusionSearchDebounceRef.current = setTimeout(() => {
      exclusionSearchRequestIdRef.current = requestActivityCaptureSearchApps(trimmed)
    }, 200)
  }

  function commitField(next: Partial<ActivityCaptureSettingsFields>, request: () => void) {
    if (!settings) return
    setSettings({ ...settings, ...next })
    request()
  }

  function handleCleanupTimeChange(value: string) {
    const [hourText, minuteText] = value.split(':')
    const cleanupHour = Number.parseInt(hourText, 10)
    const cleanupMinute = Number.parseInt(minuteText, 10)
    if (Number.isNaN(cleanupHour) || Number.isNaN(cleanupMinute)) return
    commitField({ cleanupHour, cleanupMinute }, () => requestUpdateActivityCaptureCleanupTime(cleanupHour, cleanupMinute))
  }

  function commitItemsPerRun() {
    if (!settings) return
    const parsed = Number.parseInt(itemsPerRunText.replace(/[^0-9]/g, ''), 10)
    const clamped = Number.isFinite(parsed) ? Math.min(Math.max(parsed, 0), 1000) : settings.processingMaxRecords
    setItemsPerRunText(clamped === 0 ? '' : String(clamped))
    if (clamped !== settings.processingMaxRecords) {
      commitField({ processingMaxRecords: clamped }, () => requestUpdateActivityCaptureProcessingMaxRecords(clamped))
    }
  }

  function addExclusion(bundleId: string) {
    if (!settings || settings.excludedBundleIds.includes(bundleId)) return
    setSettings({ ...settings, excludedBundleIds: [...settings.excludedBundleIds, bundleId] })
    requestAddActivityCaptureExcludedBundleId(bundleId)
  }

  function removeExclusion(bundleId: string) {
    if (!settings) return
    setSettings({ ...settings, excludedBundleIds: settings.excludedBundleIds.filter((id) => id !== bundleId) })
    requestRemoveActivityCaptureExcludedBundleId(bundleId)
  }

  function handleTestCapture() {
    if (isTestCapturing) return
    setIsTestCapturing(true)
    requestIdsRef.current.testCapture = requestActivityCaptureTestCapture()
  }

  function handleProcessBacklog() {
    if (isProcessingBacklog) return
    setIsProcessingBacklog(true)
    requestIdsRef.current.processBacklog = requestActivityCaptureProcessBacklog()
  }

  function handleCancelProcessing() {
    if (isCancelling) return
    setIsCancelling(true)
    requestIdsRef.current.cancelProcessing = requestActivityCaptureCancelProcessing()
  }

  function handleClearBacklog() {
    if (isClearingBacklog) return
    setIsClearingBacklog(true)
    requestIdsRef.current.clearBacklog = requestActivityCaptureClearBacklog()
  }

  function handleClearAllCaptures() {
    if (isClearingAll) return
    setIsClearingAll(true)
    requestIdsRef.current.clearAllCaptures = requestActivityCaptureClearAllCaptures()
  }

  if (!settings && !loadError) {
    return <p className="activity-capture-status" role="status">Loading Activity Capture settings...</p>
  }

  if (loadError) {
    return (
      <div className="activity-capture-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyActivityCaptureSettingsReady()}>Retry</button>
      </div>
    )
  }

  const current = settings!
  const localModels = availableModels.filter((model) => model.isLocal)
  const apiModels = availableModels.filter((model) => !model.isLocal)
  const selectedApiModel = apiModels.find((model) => model.id === current.processingModel)
  const cleanupTimeValue = `${String(current.cleanupHour).padStart(2, '0')}:${String(current.cleanupMinute).padStart(2, '0')}`
  const excludedBundleIdSet = new Set(current.excludedBundleIds)
  const trimmedExclusionSearch = exclusionSearchText.trim()
  const exclusionSourceApps = trimmedExclusionSearch.length === 0 ? availableApps : exclusionSearchResults
  const filteredAppOptions = exclusionSourceApps.filter((app) => !excludedBundleIdSet.has(app.bundleId))
  const showExclusionDropdown = isExclusionSearchFocused || trimmedExclusionSearch.length > 0

  return (
    <div className="activity-capture-shell">
      <section className="activity-capture-card" aria-labelledby="activity-capture-automatic-heading">
        <h3 id="activity-capture-automatic-heading">Automatic Capture</h3>
        <Switch
          id="activity-capture-enabled"
          label="Enable Automatic Capture"
          checked={current.enabled}
          onChange={(checked) => commitField({ enabled: checked }, () => requestUpdateActivityCaptureEnabled(checked))}
        />
        {current.enabled && (
          <div className="activity-capture-subcard">
            <label className="activity-capture-field-row">
              Capture Frequency
              <TokenizedSelect
                value={current.frequencySeconds}
                ariaLabel="Capture Frequency"
                onValueChange={(frequencySeconds) => {
                  commitField({ frequencySeconds }, () => requestUpdateActivityCaptureFrequencySeconds(frequencySeconds))
                }}
                options={FREQUENCY_OPTIONS.map((option) => ({ value: option.seconds, label: option.label }))}
              />
            </label>
            <p className="activity-capture-hint">Captures will be taken on this schedule while the app is running.</p>

            <label className="activity-capture-field-row">
              Skip after (seconds without input)
              <input
                type="number"
                min={0}
                max={3600}
                step={5}
                value={current.idleThresholdSeconds}
                onChange={(event) => {
                  const idleThresholdSeconds = Number(event.target.value)
                  commitField({ idleThresholdSeconds }, () => requestUpdateActivityCaptureIdleThresholdSeconds(idleThresholdSeconds))
                }}
              />
            </label>

            <label className="activity-capture-field-row">
              Wait after wake/unlock (seconds)
              <input
                type="number"
                min={0}
                max={60}
                step={1}
                value={current.postWakeGraceSeconds}
                onChange={(event) => {
                  const postWakeGraceSeconds = Number(event.target.value)
                  commitField({ postWakeGraceSeconds }, () => requestUpdateActivityCapturePostWakeGraceSeconds(postWakeGraceSeconds))
                }}
              />
            </label>
            <p className="activity-capture-hint">Automatic capture is also skipped while the screen is locked, the screen saver is active, or displays are asleep.</p>
          </div>
        )}
      </section>

      <section className="activity-capture-card" aria-labelledby="activity-capture-exclusions-heading">
        <h3 id="activity-capture-exclusions-heading">Exclusions</h3>
        <p className="activity-capture-hint">Selected apps are skipped before a screenshot is created. This applies only to automatic capture; manual, Agent Task, and Assistant Session captures are unaffected.</p>
        <div className="activity-capture-exclusions-picker">
          <div className="activity-capture-exclusions-search">
            <input
              type="text"
              className="activity-capture-exclusions-search-input"
              placeholder="Search or choose an app..."
              value={exclusionSearchText}
              onChange={(event) => handleExclusionSearchChange(event.target.value)}
              onFocus={() => { setIsExclusionSearchFocused(true); requestActivityCaptureAvailableApps() }}
              onBlur={() => setTimeout(() => setIsExclusionSearchFocused(false), 150)}
            />
          </div>
          {showExclusionDropdown && (
            <div className="activity-capture-exclusions-dropdown">
              {filteredAppOptions.length === 0 ? (
                <p className="activity-capture-hint activity-capture-exclusions-empty">No matching apps available.</p>
              ) : (
                filteredAppOptions.slice(0, 8).map((app) => (
                  <button
                    key={app.bundleId}
                    type="button"
                    className="activity-capture-exclusions-dropdown-item"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => { addExclusion(app.bundleId); handleExclusionSearchChange(''); setIsExclusionSearchFocused(false) }}
                  >
                    {app.iconDataUrl
                      ? <img src={app.iconDataUrl} alt="" className="activity-capture-exclusions-icon" />
                      : <span className="activity-capture-exclusions-icon activity-capture-exclusions-icon-placeholder" aria-hidden="true" />}
                    <span>{app.name}</span>
                  </button>
                ))
              )}
            </div>
          )}
          <div className="activity-capture-exclusions-chips">
            {current.excludedBundleIds.length === 0 ? (
              <p className="activity-capture-hint">No excluded apps selected.</p>
            ) : (
              current.excludedBundleIds.map((bundleId) => {
                const app = knownAppsByBundleId[bundleId]
                const label = app?.name ?? bundleId
                return (
                  <span key={bundleId} className="activity-capture-exclusions-chip">
                    {app?.iconDataUrl
                      ? <img src={app.iconDataUrl} alt="" className="activity-capture-exclusions-icon" />
                      : <span className="activity-capture-exclusions-icon activity-capture-exclusions-icon-placeholder" aria-hidden="true" />}
                    <span>{label}</span>
                    <button
                      type="button"
                      className="activity-capture-exclusions-chip-remove"
                      onClick={() => removeExclusion(bundleId)}
                      aria-label={`Remove ${label}`}
                    >
                      ×
                    </button>
                  </span>
                )
              })
            )}
          </div>
        </div>
      </section>

      <section className="activity-capture-card" aria-labelledby="activity-capture-processing-heading">
        <h3 id="activity-capture-processing-heading">Processing</h3>
        <label className="activity-capture-field-row">
          Processing Model
          <TokenizedSelect
            value={current.processingModel}
            disabled={availableModels.length === 0}
            ariaLabel="Processing Model"
            onValueChange={(processingModel) => commitField({ processingModel }, () => requestUpdateActivityCaptureProcessingModel(processingModel))}
            options={[
              ...(availableModels.length === 0 ? [{ value: '', label: 'No models available' }] : []),
              ...localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
              ...apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })),
            ]}
          />
        </label>
        <p className="activity-capture-hint">Choose a model for processing activity captures. Local models are recommended for high-frequency captures to reduce costs.</p>
        <p className="activity-capture-hint">
          {selectedApiModel
            ? `API model selected: captured text and image analysis may be sent to ${selectedApiModel.provider} through the configured API path. Process Backlog uses up to 8 concurrent API analyses; scheduled processing remains one at a time.`
            : 'Local model selected: captured content stays on-device for model analysis.'}
        </p>

        <label className="activity-capture-field-row">
          Processing Mode
          <TokenizedSelect
            value={current.processingMode}
            ariaLabel="Processing Mode"
            onValueChange={(processingMode) => {
              commitField({ processingMode }, () => requestUpdateActivityCaptureProcessingMode(processingMode))
            }}
            options={[
              { value: 'realtime', label: 'Real-time' },
              { value: 'scheduled', label: 'Scheduled' },
            ]}
          />
        </label>
        {current.processingMode === 'scheduled' && (
          <label className="activity-capture-field-row">
            Process at
            <input
              type="time"
              value={current.scheduledProcessingTime}
              onChange={(event) => commitField({ scheduledProcessingTime: event.target.value }, () => requestUpdateActivityCaptureScheduledProcessingTime(event.target.value))}
            />
          </label>
        )}

        <label className="activity-capture-field-row">
          Items per run
          <input type="text" value={itemsPerRunText} placeholder="All" onChange={(event) => setItemsPerRunText(event.target.value)} onBlur={commitItemsPerRun} />
        </label>
        <p className="activity-capture-hint">
          {current.processingMaxRecords === 0 ? '0 processes all eligible captures.' : `Each run processes up to ${current.processingMaxRecords} capture(s).`}
        </p>
      </section>

      {statusMessage && (
        <p className={statusMessage.startsWith('Error') ? 'activity-capture-status-message activity-capture-status-error' : 'activity-capture-status-message'}>
          {statusMessage}
        </p>
      )}

      <section className="activity-capture-card" aria-labelledby="activity-capture-status-heading">
        <h3 id="activity-capture-status-heading">Status</h3>
        <div className="activity-capture-status-columns">
          <div className="activity-capture-status-column">
            <p className="activity-capture-status-column-heading">Scheduler</p>
            <div className="activity-capture-status-row">
              <span className="activity-capture-hint">Scheduler Status</span>
              <span className={status?.isSchedulerRunning ? 'activity-capture-badge activity-capture-badge-running' : 'activity-capture-badge activity-capture-badge-stopped'}>
                {status?.isSchedulerRunning ? 'Running' : 'Stopped'}
              </span>
            </div>
            {status?.nextCaptureTime && (
              <div className="activity-capture-status-row">
                <span className="activity-capture-hint">Next Capture</span>
                <span className="activity-capture-hint">{new Date(status.nextCaptureTime).toLocaleTimeString()}</span>
              </div>
            )}
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Pending Captures</span><span className={(status?.pendingCaptures ?? 0) > 0 ? 'activity-capture-value-warning' : undefined}>{status?.pendingCaptures ?? 0}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Failed Captures</span><span className={(status?.failedCaptures ?? 0) > 0 ? 'activity-capture-value-danger' : undefined}>{status?.failedCaptures ?? 0}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Skipped by policy</span><span>{status?.skippedCaptureCount ?? 0}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Compacted duplicates</span><span>{status?.compactedCaptureCount ?? 0}</span></div>
            {status?.lastPolicyDecision && (
              <div className="activity-capture-status-row"><span className="activity-capture-hint">Last policy decision</span><span>{status.lastPolicyDecision}</span></div>
            )}
          </div>
          <div className="activity-capture-status-column">
            <p className="activity-capture-status-column-heading">Activities Captured</p>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Today</span><span>{status?.todaysCaptures ?? 0}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Last 7 Days</span><span>{status?.totalCapturesLast7Days ?? 0}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Last 30 Days</span><span>{status?.totalCapturesLast30Days ?? 0}</span></div>
            <p className="activity-capture-hint">Durable count of automatic captures recorded, independent of screenshot file retention.</p>
          </div>
        </div>
        {(status?.failedCaptures ?? 0) > 0 && <p className="activity-capture-hint">Failed captures will be retried when processing backlog.</p>}
      </section>

      <section className="activity-capture-card" aria-labelledby="activity-capture-files-heading">
        <h3 id="activity-capture-files-heading">Capture File Management</h3>
        {stats ? (
          <>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Total Files</span><span>{stats.totalFiles}</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Total Size</span><span>{(stats.totalSizeBytes / 1_000_000).toFixed(1)} MB</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Last 7 Days</span><span>{stats.filesLast7Days} files</span></div>
            <div className="activity-capture-status-row"><span className="activity-capture-hint">Last 30 Days</span><span>{stats.filesLast30Days} files</span></div>
          </>
        ) : (
          <p className="activity-capture-hint" role="status">Loading capture statistics...</p>
        )}

        <Switch
          id="activity-capture-auto-cleanup"
          label="Enable Automatic Cleanup"
          checked={current.autoCleanupEnabled}
          onChange={(checked) => commitField({ autoCleanupEnabled: checked }, () => requestUpdateActivityCaptureAutoCleanupEnabled(checked))}
        />
        {current.autoCleanupEnabled && (
          <div className="activity-capture-subcard">
            <label className="activity-capture-field-row">
              Retain Captures For
              <TokenizedSelect
                value={current.retentionDays}
                ariaLabel="Capture retention"
                onValueChange={(retentionDays) => {
                  commitField({ retentionDays }, () => requestUpdateActivityCaptureRetentionDays(retentionDays))
                }}
                options={retentionDayOptions.map((days) => ({ value: days, label: retentionLabel(days) }))}
              />
            </label>
            <label className="activity-capture-field-row">
              Cleanup Time
              <input type="time" value={cleanupTimeValue} onChange={(event) => handleCleanupTimeChange(event.target.value)} />
            </label>
            <label className="activity-capture-field-row">
              Managed Capture Storage
              <TokenizedSelect
                value={current.maxStorageMb}
                ariaLabel="Managed Capture Storage"
                onValueChange={(maxStorageMb) => {
                  commitField({ maxStorageMb }, () => requestUpdateActivityCaptureMaxStorageMb(maxStorageMb))
                }}
                options={maxStorageOptions.map((mb) => ({ value: mb, label: `${mb} MB` }))}
              />
            </label>
            <p className="activity-capture-hint">Applies to screenshots and records referenced by managed automatic capture storage, not every file on your Mac.</p>
          </div>
        )}
      </section>

      <section className="activity-capture-card" aria-labelledby="activity-capture-manual-heading">
        <h3 id="activity-capture-manual-heading">Manual Controls</h3>
        <div className="activity-capture-manual-actions">
          <button type="button" className="secondary-button" disabled={isTestCapturing} onClick={handleTestCapture}>
            {isTestCapturing ? 'Capturing…' : 'Test Capture'}
          </button>
          <button type="button" className="secondary-button" disabled={isProcessingBacklog} onClick={handleProcessBacklog}>
            {isProcessingBacklog ? 'Processing…' : 'Process Backlog'}
          </button>
        </div>
        {processingProgress?.active && (
          <div className="activity-capture-progress">
            <progress
              value={processingProgress.total > 0 ? Math.min(processingProgress.processed, processingProgress.total) : undefined}
              max={processingProgress.total > 0 ? processingProgress.total : undefined}
            />
            <p className="activity-capture-hint">{progressLine(processingProgress)}</p>
            {processingProgress.active && (
              <button type="button" className="secondary-button activity-capture-cancel-button" disabled={isCancelling || processingProgress.cancelRequested} onClick={handleCancelProcessing}>
                {isCancelling ? 'Stopping…' : 'Cancel'}
              </button>
            )}
          </div>
        )}
        <div className="activity-capture-manual-actions activity-capture-manual-actions-destructive">
          <button
            type="button"
            className="secondary-button activity-capture-destructive-button"
            disabled={isClearingBacklog || (status?.pendingCaptures === 0 && status?.failedCaptures === 0)}
            onClick={handleClearBacklog}
          >
            {isClearingBacklog ? 'Clearing…' : 'Clear Backlog'}
          </button>
          <button type="button" className="secondary-button activity-capture-destructive-button" disabled={isClearingAll} onClick={handleClearAllCaptures}>
            {isClearingAll ? 'Clearing…' : 'Clear All Captures'}
          </button>
        </div>
      </section>
    </div>
  )
}
