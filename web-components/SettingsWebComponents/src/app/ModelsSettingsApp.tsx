import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron'
import TokenizedSelect from '@shared/TokenizedSelect'
import { CustomModelsPanel } from '../components/CustomModelsPanel'
import { ReasoningApiModelsPanel } from '../components/ReasoningApiModelsPanel'
import { TranscriptionApiModelsPanel } from '../components/TranscriptionApiModelsPanel'
import {
  notifyModelsSettingsReady,
  onModelsEvent,
  requestCancelDownload,
  requestDeleteModel,
  requestDownloadModel,
  requestUpdateVisionFallback,
  requestUpdateReasoningFallback,
} from '../services/modelsBridge'
import type { ModelProviderGroup, ModelSummary } from '../types'

type CapabilityFilter = 'reasoning' | 'transcription'

interface ModelPendingRequest {
  id: string
  kind: 'download' | 'cancel' | 'delete'
}

interface StatusMessage {
  text: string
  isError: boolean
}

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return ''
  if (bytes >= 1_000_000_000) return `${(bytes / 1_000_000_000).toFixed(1)} GB`
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(0)} MB`
  return `${bytes} B`
}

export function ModelsSettingsApp() {
  const [hasLoaded, setHasLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [capabilityFilter, setCapabilityFilter] = useState<CapabilityFilter>('reasoning')
  const [transcriptionSource, setTranscriptionSource] = useState<'local' | 'api'>('local')
  const [reasoningSource, setReasoningSource] = useState<'local' | 'api' | 'custom'>('local')
  const [reasoningGroups, setReasoningGroups] = useState<ModelProviderGroup[]>([])
  const [transcriptionGroups, setTranscriptionGroups] = useState<ModelProviderGroup[]>([])
  const [isLoadingModels, setIsLoadingModels] = useState(false)
  const [visionFallbackEnabled, setVisionFallbackEnabled] = useState(false)
  const [visionFallbackInstalled, setVisionFallbackInstalled] = useState(false)
  const [visionFallbackPending, setVisionFallbackPending] = useState<string | null>(null)
  const [reasoningFallbackEnabled, setReasoningFallbackEnabled] = useState(false)
  const [reasoningFallbackModelId, setReasoningFallbackModelId] = useState('')
  const [reasoningFallbackPending, setReasoningFallbackPending] = useState<string | null>(null)
  const [pendingByModel, setPendingByModel] = useState<Record<string, ModelPendingRequest>>({})
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [logsByModel, setLogsByModel] = useState<Record<string, string[]>>({})
  const [expandedProviders, setExpandedProviders] = useState<Record<string, boolean>>({})
  const pendingRef = useRef<Record<string, ModelPendingRequest>>({})
  const visionFallbackPendingRef = useRef<string | null>(null)
  const reasoningFallbackPendingRef = useRef<string | null>(null)
  pendingRef.current = pendingByModel
  visionFallbackPendingRef.current = visionFallbackPending
  reasoningFallbackPendingRef.current = reasoningFallbackPending

  useEffect(() => {
    const unsubscribe = onModelsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setHasLoaded(true)
        setLoadError(null)
        setReasoningGroups(event.reasoningGroups)
        setTranscriptionGroups(event.transcriptionGroups)
        setIsLoadingModels(event.isLoadingModels)
        setVisionFallbackEnabled(event.localVisionFallbackEnabled)
        setVisionFallbackInstalled(event.isLocalVisionFallbackModelInstalled)
        setReasoningFallbackEnabled(event.reasoningFallbackEnabled)
        setReasoningFallbackModelId(event.reasoningFallbackModelId)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'downloadLogLine') {
        setLogsByModel((current) => {
          const existing = current[event.modelId] ?? []
          return { ...current, [event.modelId]: [...existing, event.message].slice(-20) }
        })
        return
      }
      if (event.type === 'intentResult') {
        if (event.requestId === visionFallbackPendingRef.current) {
          visionFallbackPendingRef.current = null
          setVisionFallbackPending(null)
          if (event.status === 'error') {
            setStatusMessage({ text: event.message ?? 'Failed to update Agent Vision Fallback.', isError: true })
          }
          return
        }
        if (event.requestId === reasoningFallbackPendingRef.current) {
          reasoningFallbackPendingRef.current = null
          setReasoningFallbackPending(null)
          if (event.status === 'error') {
            setStatusMessage({ text: event.message ?? 'Failed to update Reasoning Fallback.', isError: true })
          }
          return
        }
        const modelId = Object.keys(pendingRef.current).find((id) => pendingRef.current[id].id === event.requestId)
        if (!modelId) return
        const kind = pendingRef.current[modelId].kind
        const nextPending = { ...pendingRef.current }
        delete nextPending[modelId]
        pendingRef.current = nextPending
        setPendingByModel(nextPending)
        if (kind !== 'cancel') {
          setLogsByModel((current) => {
            if (!(modelId in current)) return current
            const next = { ...current }
            delete next[modelId]
            return next
          })
        }
        if (event.status === 'error') {
          setStatusMessage({ text: event.message ?? 'Something went wrong.', isError: true })
        } else if (event.status !== 'cancelled') {
          setStatusMessage(null)
        }
      }
    })
    notifyModelsSettingsReady()
    return unsubscribe
  }, [])

  function handleDownload(modelId: string) {
    if (pendingRef.current[modelId]) return
    setStatusMessage(null)
    const nextPending = { ...pendingRef.current, [modelId]: { id: requestDownloadModel(modelId), kind: 'download' as const } }
    pendingRef.current = nextPending
    setPendingByModel(nextPending)
  }

  function handleCancel(modelId: string) {
    if (pendingRef.current[modelId]) return
    const nextPending = { ...pendingRef.current, [modelId]: { id: requestCancelDownload(modelId), kind: 'cancel' as const } }
    pendingRef.current = nextPending
    setPendingByModel(nextPending)
  }

  function handleDelete(modelId: string) {
    if (pendingRef.current[modelId]) return
    setStatusMessage(null)
    const nextPending = { ...pendingRef.current, [modelId]: { id: requestDeleteModel(modelId), kind: 'delete' as const } }
    pendingRef.current = nextPending
    setPendingByModel(nextPending)
  }

  function handleVisionFallbackToggle(nextEnabled: boolean) {
    if (visionFallbackPendingRef.current) return
    setStatusMessage(null)
    const requestIdValue = requestUpdateVisionFallback(nextEnabled)
    visionFallbackPendingRef.current = requestIdValue
    setVisionFallbackPending(requestIdValue)
    setVisionFallbackEnabled(nextEnabled)
  }

  function handleReasoningFallbackChange(nextEnabled: boolean, nextModelId: string) {
    const requestIdValue = requestUpdateReasoningFallback(nextEnabled, nextModelId)
    setReasoningFallbackPending(requestIdValue)
    setReasoningFallbackEnabled(nextEnabled)
    setReasoningFallbackModelId(nextModelId)
  }

  function handleRetry() {
    notifyModelsSettingsReady()
  }

  function toggleProviderExpanded(provider: string) {
    setExpandedProviders((current) => ({ ...current, [provider]: !current[provider] }))
  }

  if (!hasLoaded && !loadError) {
    return <p className="models-settings-status" role="status">Loading model settings...</p>
  }

  if (loadError) {
    return (
      <div className="models-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={handleRetry}>Retry</button>
      </div>
    )
  }

  const activeGroups = capabilityFilter === 'reasoning' ? reasoningGroups : transcriptionGroups
  return (
    <div className="models-settings-shell">
      <div className="models-settings-filter-row" role="tablist" aria-label="Model Capability">
        <button
          type="button"
          role="tab"
          aria-selected={capabilityFilter === 'reasoning'}
          className={capabilityFilter === 'reasoning' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
          onClick={() => setCapabilityFilter('reasoning')}
        >
          Reasoning
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={capabilityFilter === 'transcription'}
          className={capabilityFilter === 'transcription' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
          onClick={() => setCapabilityFilter('transcription')}
        >
          Transcription
        </button>
      </div>

      {capabilityFilter === 'reasoning' && (
        <div className="models-settings-filter-row" role="tablist" aria-label="Reasoning Model Source">
          <button
            type="button"
            role="tab"
            aria-selected={reasoningSource === 'local'}
            className={reasoningSource === 'local' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
            onClick={() => setReasoningSource('local')}
          >
            Local Models
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={reasoningSource === 'api'}
            className={reasoningSource === 'api' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
            onClick={() => setReasoningSource('api')}
          >
            API Models
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={reasoningSource === 'custom'}
            className={reasoningSource === 'custom' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
            onClick={() => setReasoningSource('custom')}
          >
            Custom Models
          </button>
        </div>
      )}

      {capabilityFilter === 'transcription' && (
        <div className="models-settings-filter-row" role="tablist" aria-label="Transcription Model Source">
          <button
            type="button"
            role="tab"
            aria-selected={transcriptionSource === 'local'}
            className={transcriptionSource === 'local' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
            onClick={() => setTranscriptionSource('local')}
          >
            Local Models
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={transcriptionSource === 'api'}
            className={transcriptionSource === 'api' ? 'models-settings-filter-tab models-settings-filter-tab-selected' : 'models-settings-filter-tab'}
            onClick={() => setTranscriptionSource('api')}
          >
            API Models
          </button>
        </div>
      )}

      {capabilityFilter === 'reasoning' && reasoningSource === 'api' ? (
        <ReasoningApiModelsPanel />
      ) : capabilityFilter === 'reasoning' && reasoningSource === 'custom' ? (
        <CustomModelsPanel />
      ) : capabilityFilter === 'transcription' && transcriptionSource === 'api' ? (
        <TranscriptionApiModelsPanel />
      ) : isLoadingModels ? (
        <p className="models-settings-status" role="status">Loading models...</p>
      ) : activeGroups.length === 0 ? (
        <p className="models-settings-empty">No local models are available for this capability.</p>
      ) : (
        activeGroups.map((group) => {
          const isExpanded = expandedProviders[group.provider] ?? false
          const downloadedCount = group.models.filter((model) => model.statusKind === 'available' || model.statusKind === 'downloading').length
          const availableCount = group.models.length
          const listId = `models-settings-provider-list-${group.provider}`
          return (
            <section key={group.provider} className="models-settings-provider-group">
              <button
                type="button"
                className="models-settings-provider-header"
                aria-expanded={isExpanded}
                aria-controls={listId}
                onClick={() => toggleProviderExpanded(group.provider)}
              >
                <span className="models-settings-provider-chevron" aria-hidden="true">
                  <ExecutionDisclosureChevron expanded={isExpanded} color="var(--text-secondary)" />
                </span>
                <h2>{group.provider}</h2>
                <span className="models-settings-provider-counts">
                  <span className="models-settings-provider-count">{availableCount} available</span>
                  <span className="models-settings-provider-count">{downloadedCount} downloaded</span>
                </span>
              </button>
              <div className={isExpanded ? 'models-settings-provider-collapse models-settings-provider-collapse-expanded' : 'models-settings-provider-collapse'}>
                <div className="models-settings-provider-collapse-inner">
                  <ul className="models-settings-list" id={listId}>
                    {group.models.map((model) => (
                      <ModelRow
                        key={model.id}
                        model={model}
                        pendingKind={pendingByModel[model.id]?.kind ?? null}
                        logs={logsByModel[model.id] ?? []}
                        onDownload={() => handleDownload(model.id)}
                        onCancel={() => handleCancel(model.id)}
                        onDelete={() => handleDelete(model.id)}
                      />
                    ))}
                  </ul>
                </div>
              </div>
            </section>
          )
        })
      )}

      {capabilityFilter === 'reasoning' && reasoningSource === 'local' && (
        <section className="models-settings-vision-section" aria-labelledby="models-settings-vision-heading">
          <h2 id="models-settings-vision-heading">Agent Vision Fallback</h2>
          <Switch
            id="models-settings-vision-fallback-toggle"
            checked={visionFallbackEnabled}
            disabled={visionFallbackPending !== null || !visionFallbackInstalled}
            onChange={handleVisionFallbackToggle}
            label={
              visionFallbackInstalled
                ? 'When your active model has no built-in vision support, use the local Qwen2.5-VL model to analyze images.'
                : 'Download the Qwen2.5-VL local vision model above to enable this fallback.'
            }
          />
        </section>
      )}

      {capabilityFilter === 'reasoning' && reasoningSource === 'local' && (
        <section className="models-settings-vision-section" aria-labelledby="models-settings-reasoning-fallback-heading">
          <h2 id="models-settings-reasoning-fallback-heading">Reasoning Fallback When Unreachable</h2>
          <Switch
            id="models-settings-reasoning-fallback-toggle"
            checked={reasoningFallbackEnabled}
            disabled={reasoningFallbackPending !== null}
            onChange={(nextEnabled) => handleReasoningFallbackChange(nextEnabled, reasoningFallbackModelId)}
            label="If your preferred reasoning model cannot be reached at all (offline, network error, invalid API key), automatically retry once with a local model below instead of failing."
          />
          {reasoningFallbackEnabled && (
            <TokenizedSelect
              value={reasoningFallbackModelId}
              disabled={reasoningFallbackPending !== null}
              ariaLabel="Local fallback model"
              onValueChange={(modelId) => handleReasoningFallbackChange(reasoningFallbackEnabled, modelId)}
              options={[
                { value: '', label: 'Select a local model...' },
                ...reasoningGroups
                  .flatMap((group) => group.models)
                  .filter((model) => model.statusKind === 'available')
                  .map((model) => ({ value: model.id, label: model.name })),
              ]}
            />
          )}
        </section>
      )}

      {statusMessage && (
        <p className={statusMessage.isError ? 'models-settings-status-error' : 'models-settings-status-info'} role={statusMessage.isError ? 'alert' : 'status'}>
          {statusMessage.text}
        </p>
      )}
    </div>
  )
}

interface ModelRowProps {
  model: ModelSummary
  pendingKind: 'download' | 'cancel' | 'delete' | null
  logs: string[]
  onDownload: () => void
  onCancel: () => void
  onDelete: () => void
}

function ModelRow({ model, pendingKind, logs, onDownload, onCancel, onDelete }: ModelRowProps) {
  const isDownloading = model.statusKind === 'downloading'
  const isBusy = pendingKind !== null

  return (
    <li className="models-settings-row">
      <div className="models-settings-row-header">
        <span className="models-settings-row-name">{model.name}</span>
        <div className="models-settings-row-meta">
          {model.statusKind === 'available' && <span className="models-settings-installed-badge">Installed</span>}
          {model.size !== null && <span className="models-settings-row-size">{formatBytes(model.size)}</span>}
        </div>
      </div>
      <div className="models-settings-row-capabilities">
        <div className="models-settings-row-capabilities-chips">
          {model.capabilities.map((capability) => (
            <span key={capability} className="models-settings-capability-chip">{capability}</span>
          ))}
        </div>
        {model.statusKind === 'available' && (
          <button type="button" className="models-settings-delete-button" disabled={isBusy} onClick={onDelete}>
            {pendingKind === 'delete' ? 'Deleting...' : 'Delete'}
          </button>
        )}
        {model.statusKind === 'downloadable' && (
          <button type="button" className="secondary-button" disabled={isBusy} onClick={onDownload}>
            {pendingKind === 'download' ? 'Starting...' : 'Download'}
          </button>
        )}
      </div>

      {isDownloading ? (
        <div className="models-settings-progress-row">
          <div className="models-settings-progress-track">
            <div className="models-settings-progress-fill" style={{ width: `${Math.round((model.progress ?? 0) * 100)}%` }} />
          </div>
          <span className="models-settings-progress-label">{Math.round((model.progress ?? 0) * 100)}%</span>
          <button type="button" className="models-settings-cancel-button" disabled={pendingKind === 'cancel'} onClick={onCancel}>
            Cancel
          </button>
        </div>
      ) : model.statusKind === 'error' ? (
        <div className="models-settings-error-row">
          <span className="models-settings-error-message">{model.errorMessage}</span>
          <button type="button" className="secondary-button" disabled={isBusy} onClick={onDownload}>Retry</button>
        </div>
      ) : null}

      {isDownloading && logs.length > 0 && (
        <div className="models-settings-log-tail" aria-live="polite">
          {logs.slice(-3).map((line, index) => <div key={index} className="models-settings-log-line">{line}</div>)}
        </div>
      )}
    </li>
  )
}
