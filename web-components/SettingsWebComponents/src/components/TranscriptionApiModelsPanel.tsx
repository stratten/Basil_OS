import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import {
  notifyTranscriptionApiModelsReady,
  onTranscriptionApiModelsEvent,
  requestSaveApiKey,
  requestToggleMaster,
  requestToggleModel,
  requestToggleProvider,
} from '../services/transcriptionApiModelsBridge'
import type { TranscriptionApiModelSummary } from '../types'

interface StatusMessage {
  text: string
  isError: boolean
}

export function TranscriptionApiModelsPanel() {
  const [hasLoaded, setHasLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [useApiTranscriptionModels, setUseApiTranscriptionModels] = useState(false)
  const [openaiEnabled, setOpenaiEnabled] = useState(false)
  const [openaiHasKey, setOpenaiHasKey] = useState(false)
  const [models, setModels] = useState<TranscriptionApiModelSummary[]>([])
  const [apiKeyInput, setApiKeyInput] = useState('')
  const [keyMessage, setKeyMessage] = useState<StatusMessage | null>(null)
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [masterPending, setMasterPending] = useState<string | null>(null)
  const [providerPending, setProviderPending] = useState<string | null>(null)
  const [keyPending, setKeyPending] = useState<string | null>(null)
  const [pendingModelIds, setPendingModelIds] = useState<Record<string, string>>({})
  const masterPendingRef = useRef<string | null>(null)
  const providerPendingRef = useRef<string | null>(null)
  const keyPendingRef = useRef<string | null>(null)
  const pendingModelsRef = useRef<Record<string, string>>({})
  masterPendingRef.current = masterPending
  providerPendingRef.current = providerPending
  keyPendingRef.current = keyPending
  pendingModelsRef.current = pendingModelIds

  useEffect(() => {
    const unsubscribe = onTranscriptionApiModelsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setHasLoaded(true)
        setLoadError(null)
        setIsLoading(event.isLoading)
        setUseApiTranscriptionModels(event.useApiTranscriptionModels)
        setOpenaiEnabled(event.openaiEnabled)
        setOpenaiHasKey(event.openaiHasKey)
        setModels(event.models)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') {
        handleIntentResult(event)
      }
    })
    notifyTranscriptionApiModelsReady()
    return unsubscribe
  }, [])

  function handleIntentResult(event: { requestId: string; status: 'success' | 'error'; message?: string }) {
    if (event.requestId === masterPendingRef.current) {
      masterPendingRef.current = null
      setMasterPending(null)
      setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update API transcription models.', isError: true } : null)
      return
    }
    if (event.requestId === providerPendingRef.current) {
      providerPendingRef.current = null
      setProviderPending(null)
      setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update the OpenAI provider.', isError: true } : null)
      return
    }
    if (event.requestId === keyPendingRef.current) {
      keyPendingRef.current = null
      setKeyPending(null)
      if (event.status === 'success') {
        setApiKeyInput('')
        setKeyMessage({ text: event.message ?? 'API key is valid and saved', isError: false })
      } else {
        setKeyMessage({ text: event.message ?? 'Failed to save API key.', isError: true })
      }
      return
    }
    const modelId = Object.keys(pendingModelsRef.current).find((id) => pendingModelsRef.current[id] === event.requestId)
    if (!modelId) return
    const nextPending = { ...pendingModelsRef.current }
    delete nextPending[modelId]
    pendingModelsRef.current = nextPending
    setPendingModelIds(nextPending)
    setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update the model.', isError: true } : null)
  }

  function handleToggleMaster(next: boolean) {
    if (masterPendingRef.current) return
    setStatusMessage(null)
    const id = requestToggleMaster(next)
    masterPendingRef.current = id
    setMasterPending(id)
    setUseApiTranscriptionModels(next)
  }

  function handleToggleProvider(next: boolean) {
    if (providerPendingRef.current) return
    setStatusMessage(null)
    const id = requestToggleProvider(next)
    providerPendingRef.current = id
    setProviderPending(id)
    setOpenaiEnabled(next)
  }

  function handleSaveKey() {
    if (keyPendingRef.current || apiKeyInput.length === 0) return
    setKeyMessage(null)
    const id = requestSaveApiKey(apiKeyInput)
    keyPendingRef.current = id
    setKeyPending(id)
  }

  function handleToggleModel(modelId: string, next: boolean) {
    if (pendingModelsRef.current[modelId]) return
    setStatusMessage(null)
    const id = requestToggleModel(modelId, next)
    const nextMap = { ...pendingModelsRef.current, [modelId]: id }
    pendingModelsRef.current = nextMap
    setPendingModelIds(nextMap)
  }

  function handleRetry() {
    notifyTranscriptionApiModelsReady()
  }

  if (!hasLoaded && !loadError) {
    return <p className="transcription-api-models-status" role="status">Loading transcription API models...</p>
  }

  if (loadError) {
    return (
      <div className="transcription-api-models-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={handleRetry}>Retry</button>
      </div>
    )
  }

  return (
    <div className="transcription-api-models-panel">
      <Switch
        id="transcription-api-models-master-toggle"
        checked={useApiTranscriptionModels}
        disabled={masterPending !== null}
        onChange={handleToggleMaster}
        label="Use API Transcription Models"
      />

      {useApiTranscriptionModels && (
        isLoading ? (
          <p className="transcription-api-models-status" role="status">Loading transcription API models...</p>
        ) : (
          <div className="transcription-api-models-provider">
            <div className="transcription-api-models-provider-header">
              <span className="transcription-api-models-provider-name">OpenAI</span>
              <Switch
                id="transcription-api-models-provider-toggle"
                checked={openaiEnabled}
                disabled={providerPending !== null}
                onChange={handleToggleProvider}
                label=""
              />
            </div>

            {openaiEnabled && (
              <>
                <div className="transcription-api-models-key-section">
                  {openaiHasKey && (
                    <p className="transcription-api-models-key-active">
                      Your OpenAI API key is active and ready to use. This is the same key used by reasoning models.
                    </p>
                  )}
                  <div className="transcription-api-models-key-row">
                    <input
                      type="password"
                      className="transcription-api-models-key-input"
                      value={apiKeyInput}
                      disabled={keyPending !== null}
                      placeholder={openaiHasKey ? 'Update OpenAI API Key' : 'Enter OpenAI API Key'}
                      onChange={(event) => setApiKeyInput(event.target.value)}
                    />
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={keyPending !== null || apiKeyInput.length === 0}
                      onClick={handleSaveKey}
                    >
                      {keyPending !== null ? 'Validating...' : openaiHasKey ? 'Update Key' : 'Save & Validate'}
                    </button>
                  </div>
                  {keyMessage && (
                    <p
                      className={keyMessage.isError ? 'transcription-api-models-status-error' : 'transcription-api-models-status-success'}
                      role={keyMessage.isError ? 'alert' : 'status'}
                    >
                      {keyMessage.text}
                    </p>
                  )}
                </div>

                <ul className="transcription-api-models-list">
                  {models.map((model) => (
                    <li key={model.id} className="transcription-api-models-row">
                      <div className="transcription-api-models-row-text">
                        <span className="transcription-api-models-row-name">{model.displayName}</span>
                        <span className="transcription-api-models-row-description">{model.description}</span>
                      </div>
                      <Switch
                        id={`transcription-api-models-toggle-${model.id}`}
                        checked={model.enabled}
                        disabled={pendingModelIds[model.id] !== undefined}
                        onChange={(next) => handleToggleModel(model.id, next)}
                        label=""
                      />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )
      )}

      {statusMessage && (
        <p
          className={statusMessage.isError ? 'transcription-api-models-status-error' : 'transcription-api-models-status-success'}
          role={statusMessage.isError ? 'alert' : 'status'}
        >
          {statusMessage.text}
        </p>
      )}
    </div>
  )
}
