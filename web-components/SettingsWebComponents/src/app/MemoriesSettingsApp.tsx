import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import type { MemoriesNarrativeProgress, MemoriesProcessingModelOption, MemoriesSettingsFields, MemoriesStatsData } from '../types'
import {
  notifyMemoriesSettingsReady,
  onMemoriesEvent,
  requestCancelSummarize,
  requestCollectNow,
  requestNarrativeProgress,
  requestRefreshStats,
  requestRetryFailedSummaries,
  requestSummarizeNow,
  requestUpdateMemoriesSettings,
} from '../services/memoriesSettingsBridge'

const SOURCE_OPTIONS: readonly { kind: string; label: string }[] = [
  { kind: 'agent_task', label: 'Agent tasks' },
  { kind: 'transcription', label: 'Transcriptions' },
  { kind: 'assistant_output', label: 'Assistant outputs' },
  { kind: 'scheduled_run', label: 'Scheduled runs' },
  { kind: 'conversation', label: 'Conversations' },
  { kind: 'screen_block', label: 'Screen activity' },
  { kind: 'meeting', label: 'Meetings' },
]
const CARDING_INTERVAL_OPTIONS = [5, 10, 15, 30, 60, 120]
const HISTORY_DAY_OPTIONS = [0, 7, 14, 30, 60, 90, 180, 365]
const NARRATIVE_INTERVAL_OPTIONS = [15, 30, 60, 120, 240]
const MAX_ATTEMPT_OPTIONS = [1, 2, 3, 5]

function intervalLabel(minutes: number): string {
  return minutes >= 60 ? `${minutes / 60} hour${minutes >= 120 ? 's' : ''}` : `${minutes} minutes`
}

function historyLabel(days: number): string {
  return days === 0 ? 'All history' : `Last ${days} days`
}

function progressLine(progress: MemoriesNarrativeProgress): string {
  const parts = [`${progress.processed} of ${progress.total} summarized`]
  if (progress.processingStrategy === 'api_parallel' && progress.analysisConcurrency) {
    parts.push(`up to ${progress.analysisConcurrency} at once`)
  }
  if (progress.failed > 0) parts.push(`${progress.failed} failed`)
  parts.push(`${progress.remaining} remaining`)
  if (progress.canceling) {
    parts.push(progress.processingStrategy === 'api_parallel' ? 'stopping after items in progress' : 'stopping after this item')
  } else if (progress.etaSeconds && progress.etaSeconds > 0) {
    const minutes = Math.ceil(progress.etaSeconds / 60)
    parts.push(minutes <= 1 ? '~1 min left' : `~${minutes} min left`)
  }
  return parts.join(' \u00B7 ')
}

interface PendingRequestIds {
  collect?: string
  summarize?: string
  retry?: string
  cancel?: string
  refresh?: string
}

export function MemoriesSettingsApp() {
  const [settings, setSettings] = useState<MemoriesSettingsFields | null>(null)
  const [stats, setStats] = useState<MemoriesStatsData | null>(null)
  const [narrativeProgress, setNarrativeProgress] = useState<MemoriesNarrativeProgress | null>(null)
  const [availableModels, setAvailableModels] = useState<MemoriesProcessingModelOption[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [maxRecordsText, setMaxRecordsText] = useState('')
  const [isRunningCarding, setIsRunningCarding] = useState(false)
  const [isRunningNarrative, setIsRunningNarrative] = useState(false)
  const [isRetryingFailed, setIsRetryingFailed] = useState(false)
  const [isCanceling, setIsCanceling] = useState(false)
  const [isLoadingStats, setIsLoadingStats] = useState(false)
  const [completedNarrativeProgress, setCompletedNarrativeProgress] = useState<MemoriesNarrativeProgress | null>(null)
  const [collectionCompletionMessage, setCollectionCompletionMessage] = useState<string | null>(null)
  const sawActiveRef = useRef(false)
  const pollsBeforeStartRef = useRef(0)
  const pollTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestIdsRef = useRef<PendingRequestIds>({})

  function startProgressPolling() {
    sawActiveRef.current = false
    pollsBeforeStartRef.current = 0
    setCompletedNarrativeProgress(null)
    setIsRunningNarrative(true)
    pollOnce()
  }

  function pollOnce() {
    requestNarrativeProgress()
    pollTimeoutRef.current = setTimeout(pollOnce, 1200)
  }

  function stopProgressPolling() {
    if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current)
    pollTimeoutRef.current = null
  }

  function showStatus(message: string) {
    setStatusMessage(message)
    setTimeout(() => setStatusMessage((current) => (current === message ? null : current)), 5000)
  }

  useEffect(() => {
    const unsubscribe = onMemoriesEvent((event) => {
      if (event.type === 'init') {
        setSettings(event.settings)
        setStats(event.stats)
        setNarrativeProgress(event.narrativeProgress)
        setAvailableModels(event.availableModels)
        setMaxRecordsText(event.settings.narrativeMaxRecords === 0 ? '' : String(event.settings.narrativeMaxRecords))
        setLoadError(null)
        if (event.narrativeProgress?.active) startProgressPolling()
      } else if (event.type === 'snapshot') {
        setSettings(event.settings)
        setStats(event.stats)
        setAvailableModels(event.availableModels)
      } else if (event.type === 'progress') {
        setNarrativeProgress(event.narrativeProgress)
        if (event.narrativeProgress.active) {
          sawActiveRef.current = true
        } else if (sawActiveRef.current) {
          stopProgressPolling()
          setIsRunningNarrative(false)
          setCompletedNarrativeProgress(event.narrativeProgress)
          setIsLoadingStats(true)
          requestIdsRef.current.refresh = requestRefreshStats()
        } else {
          pollsBeforeStartRef.current += 1
          if (pollsBeforeStartRef.current > 5) {
            stopProgressPolling()
            setIsRunningNarrative(false)
          }
        }
      } else if (event.type === 'intentResult') {
        const ids = requestIdsRef.current
        if (event.requestId === ids.collect) {
          setIsRunningCarding(false)
          if (event.status === 'success') {
            setCollectionCompletionMessage('Collection completed.')
          } else if (event.message) {
            showStatus(event.message)
          }
        } else if (event.requestId === ids.summarize) {
          if (event.status === 'error') {
            stopProgressPolling()
            setIsRunningNarrative(false)
          }
          if (event.message) showStatus(event.message)
        } else if (event.requestId === ids.retry) {
          setIsRetryingFailed(false)
          if (event.message) showStatus(event.message)
        } else if (event.requestId === ids.cancel) {
          setIsCanceling(false)
          if (event.message) showStatus(event.message)
        } else if (event.requestId === ids.refresh) {
          setIsLoadingStats(false)
        } else if (event.status === 'error' && event.message) {
          showStatus(event.message)
        }
      } else if (event.type === 'loadError') {
        setLoadError(event.message)
      }
    })
    notifyMemoriesSettingsReady()
    return () => {
      unsubscribe()
      stopProgressPolling()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function updateSettings(next: MemoriesSettingsFields) {
    setSettings(next)
    requestUpdateMemoriesSettings(next)
  }

  function toggleSource(kind: string, enabled: boolean) {
    if (!settings) return
    const enabledSources = enabled
      ? [...settings.enabledSources, kind]
      : settings.enabledSources.filter((existing) => existing !== kind)
    updateSettings({ ...settings, enabledSources })
  }

  function commitMaxRecords() {
    if (!settings) return
    const trimmed = maxRecordsText.trim()
    const parsed = Number.parseInt(trimmed, 10)
    const narrativeMaxRecords = Number.isFinite(parsed) && parsed > 0 ? Math.min(parsed, 100000) : 0
    setMaxRecordsText(narrativeMaxRecords === 0 ? '' : String(narrativeMaxRecords))
    updateSettings({ ...settings, narrativeMaxRecords })
  }

  function handleCollectNow() {
    if (isRunningCarding) return
    setCollectionCompletionMessage(null)
    setIsRunningCarding(true)
    requestIdsRef.current.collect = requestCollectNow()
  }

  function handleSummarizeNow() {
    if (isRunningNarrative) return
    requestIdsRef.current.summarize = requestSummarizeNow()
    startProgressPolling()
  }

  function handleRetryFailed() {
    if (isRetryingFailed) return
    setIsRetryingFailed(true)
    requestIdsRef.current.retry = requestRetryFailedSummaries()
  }

  function handleCancel() {
    if (isCanceling) return
    setIsCanceling(true)
    requestIdsRef.current.cancel = requestCancelSummarize()
  }

  function handleRefreshStats() {
    if (isLoadingStats) return
    setIsLoadingStats(true)
    requestIdsRef.current.refresh = requestRefreshStats()
  }

  if (!settings && !loadError) {
    return <p className="memories-status" role="status">Loading Memories settings...</p>
  }

  if (loadError) {
    return (
      <div className="memories-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyMemoriesSettingsReady()}>Retry</button>
      </div>
    )
  }

  const current = settings!
  const localModels = availableModels.filter((model) => model.isLocal)
  const apiModels = availableModels.filter((model) => !model.isLocal)

  return (
    <div className="memories-shell">
      <p className="memories-intro">
        Everything you do in Basil is folded into one chronological log, then summarized into a short recap so you can ask things like &quot;what did I do yesterday?&quot;
      </p>

      <section className="memories-card" aria-labelledby="memories-progress-heading">
        <h3 id="memories-progress-heading">Progress</h3>
        {stats ? (
          <>
            <div className={stats.awaitingRetry > 0 ? 'memories-metrics-grid memories-metrics-grid-with-retry' : 'memories-metrics-grid'}>
              <MetricTile title="Collected" value={stats.collected} />
              <MetricTile title="Waiting to collect" value={stats.awaitingCollection} />
              <MetricTile title="Summarized" value={stats.summarized} />
              <MetricTile title="Awaiting summary" value={stats.awaitingSummary} />
              {stats.awaitingRetry > 0 && <MetricTile title="Needs retry" value={stats.awaitingRetry} accent="warning" />}
              {stats.failed > 0 && <MetricTile title="Couldn't summarize" value={stats.failed} accent="danger" />}
            </div>
            {(stats.failed > 0 || stats.awaitingRetry > 0) && (
              <div className="memories-inline-action">
                <button type="button" className="secondary-button" disabled={isRetryingFailed || isRunningNarrative} onClick={handleRetryFailed}>
                  {isRetryingFailed ? 'Resetting…' : 'Reset unfinished summaries'}
                </button>
                <p className="memories-hint">Resets failed and retry-exhausted summaries so they can be processed again. Completed summaries are unchanged.</p>
              </div>
            )}
            {stats.bySource.length > 0 && (
              <ul className="memories-source-stats">
                {stats.bySource.map((source) => (
                  <li key={source.kind}>
                    <span>{SOURCE_OPTIONS.find((option) => option.kind === source.kind)?.label ?? source.kind}</span>
                    <span className="memories-hint">{source.collected} collected · {source.awaitingCollection} waiting</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="memories-hint">Loading counts…</p>
        )}
        <button type="button" className="secondary-button" disabled={isLoadingStats} onClick={handleRefreshStats}>
          {isLoadingStats ? 'Refreshing…' : 'Refresh'}
        </button>
      </section>

      <section className="memories-card" aria-labelledby="memories-collecting-heading">
        <h3 id="memories-collecting-heading">Collecting</h3>
        <Switch id="memories-collect-automatically" label="Collect automatically" checked={current.cardingEnabled} onChange={(checked) => updateSettings({ ...current, cardingEnabled: checked })} />
        <p className="memories-hint">Collection adds eligible activity to your timeline without using a model. Summary processing later uses your selected model to turn collected activity into short recaps.</p>
        {current.cardingEnabled && (
          <div className="memories-subcard">
            <label className="memories-field-row">
              Run every
              <TokenizedSelect
                value={current.cardingIntervalMinutes}
                ariaLabel="Collection interval"
                onValueChange={(cardingIntervalMinutes) => updateSettings({ ...current, cardingIntervalMinutes })}
                options={CARDING_INTERVAL_OPTIONS.map((minutes) => ({ value: minutes, label: intervalLabel(minutes) }))}
              />
            </label>
            <label className="memories-field-row">
              Include history
              <TokenizedSelect
                value={current.historyDays}
                ariaLabel="Collection history"
                onValueChange={(historyDays) => updateSettings({ ...current, historyDays })}
                options={HISTORY_DAY_OPTIONS.map((days) => ({ value: days, label: historyLabel(days) }))}
              />
            </label>
            <p className="memories-hint">Older items are only collected once they fall inside this window.</p>
          </div>
        )}
        <button type="button" className="secondary-button" disabled={isRunningCarding} onClick={handleCollectNow}>
          {isRunningCarding ? 'Collecting…' : 'Collect now'}
        </button>
        {collectionCompletionMessage && (
          <p className="memories-collection-completion" role="status">{collectionCompletionMessage}</p>
        )}
      </section>

      <section className="memories-card" aria-labelledby="memories-sources-heading">
        <h3 id="memories-sources-heading">Included Sources</h3>
        <p className="memories-hint">Choose which kinds of activity are folded into the stream.</p>
        <div className="memories-selectable-chip-group">
          {SOURCE_OPTIONS.map((option) => (
            <label key={option.kind} className="memories-selectable-chip">
              <input
                type="checkbox"
                checked={current.enabledSources.includes(option.kind)}
                onChange={(event) => toggleSource(option.kind, event.target.checked)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="memories-card" aria-labelledby="memories-summaries-heading">
        <h3 id="memories-summaries-heading">Summaries</h3>
        <Switch id="memories-summarize-automatically" label="Summarize automatically" checked={current.narrativeEnabled} onChange={(checked) => updateSettings({ ...current, narrativeEnabled: checked })} />
        <p className="memories-hint">A model writes a short summary of each item — what an agent task accomplished, what a conversation covered, and so on.</p>
        {current.narrativeEnabled && (
          <div className="memories-subcard">
            <label className="memories-field-row">
              Model
              <TokenizedSelect
                value={current.narrativeModel}
                ariaLabel="Narrative model"
                onValueChange={(narrativeModel) => updateSettings({ ...current, narrativeModel })}
                options={[
                  { value: '', label: 'Default reasoning model' },
                  ...localModels.map((model) => ({ value: model.id, label: model.displayName, group: 'Local Models' })),
                  ...apiModels.map((model) => ({ value: model.id, label: model.displayName, group: 'API Models' })),
                ]}
              />
            </label>
            <p className="memories-hint">A local model is recommended so background summarization does not incur API cost.</p>

            <label className="memories-field-row">
              Mode
              <TokenizedSelect
                value={current.narrativeMode}
                ariaLabel="Narrative mode"
                onValueChange={(narrativeMode) => updateSettings({ ...current, narrativeMode })}
                options={[
                  { value: 'scheduled', label: 'Scheduled (daily)' },
                  { value: 'continuous', label: 'Continuous (interval)' },
                ]}
              />
            </label>
            {current.narrativeMode === 'scheduled' ? (
              <label className="memories-field-row">
                Run at
                <input type="time" value={current.narrativeScheduledTime} onChange={(event) => updateSettings({ ...current, narrativeScheduledTime: event.target.value })} />
              </label>
            ) : (
              <label className="memories-field-row">
                Run every
                <TokenizedSelect
                  value={current.narrativeIntervalMinutes}
                  ariaLabel="Narrative interval"
                  onValueChange={(narrativeIntervalMinutes) => updateSettings({ ...current, narrativeIntervalMinutes })}
                  options={NARRATIVE_INTERVAL_OPTIONS.map((minutes) => ({ value: minutes, label: intervalLabel(minutes) }))}
                />
              </label>
            )}

            <label className="memories-field-row">
              Items per run
              <input type="text" value={maxRecordsText} placeholder="All" onChange={(event) => setMaxRecordsText(event.target.value)} onBlur={commitMaxRecords} />
            </label>
            <p className="memories-hint">How many items a single run will summarize before stopping. Leave blank to process everything.</p>

            <label className="memories-field-row">
              Retries before giving up
              <TokenizedSelect
                value={current.narrativeMaxAttempts}
                ariaLabel="Narrative retry limit"
                onValueChange={(narrativeMaxAttempts) => updateSettings({ ...current, narrativeMaxAttempts })}
                options={MAX_ATTEMPT_OPTIONS.map((attempts) => ({ value: attempts, label: String(attempts) }))}
              />
            </label>

            <button type="button" className="secondary-button" disabled={isRunningNarrative} onClick={handleSummarizeNow}>
              {isRunningNarrative ? 'Summarizing…' : 'Summarize now'}
            </button>

            {completedNarrativeProgress && (
              <p className="memories-summary-completion" role="status">
                {completedNarrativeProgress.canceling
                  ? `Summarization stopped after ${completedNarrativeProgress.finalized} finalized.`
                  : completedNarrativeProgress.failed > 0
                    ? `Summary pass finished: ${completedNarrativeProgress.finalized} finalized and ${completedNarrativeProgress.failed} need attention.`
                    : `Summary pass complete: ${completedNarrativeProgress.finalized} finalized.`}
              </p>
            )}

            {narrativeProgress?.active && (
              <div className="memories-progress">
                <progress value={narrativeProgress.total > 0 ? Math.min(narrativeProgress.processed, narrativeProgress.total) : undefined} max={narrativeProgress.total > 0 ? narrativeProgress.total : undefined} />
                <p className="memories-hint">{progressLine(narrativeProgress)}</p>
                {narrativeProgress.active && (
                  <button type="button" className="secondary-button memories-cancel-button" disabled={isCanceling || Boolean(narrativeProgress.canceling)} onClick={handleCancel}>
                    {isCanceling ? 'Stopping…' : 'Cancel'}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </section>

      {statusMessage && (
        <p className={statusMessage.startsWith('Error') ? 'memories-status-message memories-status-error' : 'memories-status-message'}>
          {statusMessage}
        </p>
      )}
    </div>
  )
}

function MetricTile({ title, value, accent }: { title: string; value: number; accent?: 'warning' | 'danger' }) {
  return (
    <div className={accent ? `memories-metric-tile memories-metric-${accent}` : 'memories-metric-tile'}>
      <span className="memories-metric-value">{value}</span>
      <span className="memories-metric-title">{title}</span>
    </div>
  )
}