import { useEffect, useRef, useState } from 'react'
import PresenceRegion from '@shared/PresenceRegion'
import {
  notifyCustomModelsReady,
  onCustomModelsEvent,
  requestDeleteModel,
  requestDownloadModel,
  requestTestConnection,
} from '../services/customModelsBridge'
import { CustomModelRow } from './customModels/CustomModelRow'
import { CustomModelWizard } from './customModels/CustomModelWizard'
import { CustomModelEditForm } from './customModels/CustomModelEditForm'
import type { CustomModelSummary, CustomModelsNativeEvent } from '../types'

interface StatusMessage {
  text: string
  isError: boolean
}

function PanelIcon({ kind }: { kind: 'models' | 'add' }) {
  return kind === 'models'
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2" /><path d="M8 9h8M8 13h5" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 8v8M8 12h8" /></svg>
}

export interface LatestBridgeEvent {
  event: CustomModelsNativeEvent
  seq: number
}

export function CustomModelsPanel() {
  const [hasLoaded, setHasLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [models, setModels] = useState<CustomModelSummary[]>([])
  const [showWizard, setShowWizard] = useState(false)
  const [editingModel, setEditingModel] = useState<CustomModelSummary | null>(null)
  const [deletePendingByModel, setDeletePendingByModel] = useState<Record<string, string>>({})
  const [downloadPendingByModel, setDownloadPendingByModel] = useState<Record<string, string>>({})
  const [liveDownload, setLiveDownload] = useState<Record<string, { progress: number; status: string }>>({})
  const [connectionTestByModel, setConnectionTestByModel] = useState<Record<string, { success: boolean; message: string }>>({})
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [latestEvent, setLatestEvent] = useState<LatestBridgeEvent | null>(null)

  const deletePendingRef = useRef(deletePendingByModel)
  const downloadPendingRef = useRef(downloadPendingByModel)
  const connectionTestPendingRef = useRef<Record<string, string>>({})
  const seqRef = useRef(0)
  deletePendingRef.current = deletePendingByModel
  downloadPendingRef.current = downloadPendingByModel

  useEffect(() => {
    const unsubscribe = onCustomModelsEvent((event) => {
      seqRef.current += 1
      setLatestEvent({ event, seq: seqRef.current })

      if (event.type === 'init' || event.type === 'snapshot') {
        setHasLoaded(true)
        setLoadError(null)
        setIsLoading(event.isLoading)
        setModels(event.models)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'downloadProgress') {
        setLiveDownload((current) => ({ ...current, [event.modelId]: { progress: event.progress, status: event.status } }))
        return
      }
      if (event.type === 'connectionTestResult') {
        const modelId = connectionTestPendingRef.current[event.requestId]
        if (modelId) {
          delete connectionTestPendingRef.current[event.requestId]
          setConnectionTestByModel((current) => ({ ...current, [modelId]: { success: event.success, message: event.message } }))
        }
        return
      }
      if (event.type === 'intentResult') {
        const deleteModelId = Object.keys(deletePendingRef.current).find((id) => deletePendingRef.current[id] === event.requestId)
        if (deleteModelId) {
          const next = { ...deletePendingRef.current }
          delete next[deleteModelId]
          deletePendingRef.current = next
          setDeletePendingByModel(next)
          if (event.status === 'error') setStatusMessage({ text: event.message ?? 'Failed to delete the model.', isError: true })
          return
        }
        const downloadModelId = Object.keys(downloadPendingRef.current).find((id) => downloadPendingRef.current[id] === event.requestId)
        if (downloadModelId) {
          const next = { ...downloadPendingRef.current }
          delete next[downloadModelId]
          downloadPendingRef.current = next
          setDownloadPendingByModel(next)
          setLiveDownload((current) => {
            if (!(downloadModelId in current)) return current
            const nextLive = { ...current }
            delete nextLive[downloadModelId]
            return nextLive
          })
          if (event.status === 'error') setStatusMessage({ text: event.message ?? 'Download failed.', isError: true })
        }
      }
    })
    notifyCustomModelsReady()
    return unsubscribe
  }, [])

  function handleDelete(modelId: string, deleteFiles: boolean, clearHFCache: boolean) {
    const requestId = requestDeleteModel(modelId, deleteFiles, clearHFCache)
    setDeletePendingByModel((current) => ({ ...current, [modelId]: requestId }))
  }

  function handleDownload(modelId: string, filename: string) {
    const requestId = requestDownloadModel(modelId, filename)
    setDownloadPendingByModel((current) => ({ ...current, [modelId]: requestId }))
  }

  function handleTestConnection(model: CustomModelSummary) {
    if (!model.baseUrl || !model.modelIdentifier) return
    const requestId = requestTestConnection({ handler: model.handler, baseUrl: model.baseUrl, modelIdentifier: model.modelIdentifier })
    connectionTestPendingRef.current[requestId] = model.modelId
  }

  function filenameFromDownloadUrl(downloadUrl: string): string | null {
    if (downloadUrl.includes('/resolve/') || downloadUrl.includes('/blob/')) {
      try {
        const url = new URL(downloadUrl)
        const segments = url.pathname.split('/').filter(Boolean)
        return segments[segments.length - 1] ?? null
      } catch {
        return null
      }
    }
    return null
  }

  function handleDownloadClick(model: CustomModelSummary) {
    if (!model.downloadUrl) return
    const filename = filenameFromDownloadUrl(model.downloadUrl)
    if (!filename) {
      setStatusMessage({ text: 'Cannot determine which file to download. Edit the model and enter a specific file URL.', isError: true })
      return
    }
    handleDownload(model.modelId, filename)
  }

  if (!hasLoaded && !loadError) {
    return <p className="models-settings-status custom-models-status" role="status">Loading custom models...</p>
  }
  if (loadError) {
    return (
      <div className="custom-models-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={notifyCustomModelsReady}>Retry</button>
      </div>
    )
  }

  return (
    <div className="custom-models-panel">
      <div className="custom-models-header">
        <div className="custom-models-header-content">
          <span className="custom-models-header-icon"><PanelIcon kind="models" /></span>
          <div>
            <h2>Custom Models</h2>
            <p>Manage local GGUF files and compatible remote endpoints.</p>
          </div>
        </div>
        <button type="button" className="custom-models-add-button" onClick={() => setShowWizard(true)}>
          <PanelIcon kind="add" />
          Add Model
        </button>
      </div>

      {statusMessage && (
        <p className={statusMessage.isError ? 'custom-models-status-message custom-models-status-message-error' : 'custom-models-status-message'} role={statusMessage.isError ? 'alert' : 'status'}>
          {statusMessage.text}
        </p>
      )}

      {isLoading && models.length === 0 ? (
        <p className="custom-models-status" role="status">Loading custom models...</p>
      ) : models.length === 0 ? (
        <div className="custom-models-empty">
          <span className="custom-models-empty-icon"><PanelIcon kind="models" /></span>
          <p>No custom models yet.</p>
          <p className="custom-models-empty-hint">Add local GGUF models or connect to API endpoints.</p>
          <button type="button" className="custom-models-add-button" onClick={() => setShowWizard(true)}>
            <PanelIcon kind="add" />
            Add Custom Model
          </button>
        </div>
      ) : (
        <ul className="custom-models-list">
          {models.map((model) => (
            <CustomModelRow
              key={model.modelId}
              model={model}
              isDeleting={model.modelId in deletePendingByModel}
              isDownloading={model.modelId in downloadPendingByModel || model.modelId in liveDownload}
              liveDownload={liveDownload[model.modelId] ?? null}
              connectionTestResult={connectionTestByModel[model.modelId] ?? null}
              onEdit={() => setEditingModel(model)}
              onDelete={(deleteFiles, clearHFCache) => handleDelete(model.modelId, deleteFiles, clearHFCache)}
              onDownload={() => handleDownloadClick(model)}
              onTestConnection={() => handleTestConnection(model)}
            />
          ))}
        </ul>
      )}

      <PresenceRegion visible={showWizard} className="custom-models-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        <CustomModelWizard latestEvent={latestEvent} onDismiss={() => setShowWizard(false)} />
      </PresenceRegion>

      <PresenceRegion visible={editingModel !== null} className="custom-models-modal-overlay basil-presence--modal" role="presentation" settleWithoutTransition>
        {editingModel && (
          <CustomModelEditForm model={editingModel} latestEvent={latestEvent} onDismiss={() => setEditingModel(null)} />
        )}
      </PresenceRegion>
    </div>
  )
}