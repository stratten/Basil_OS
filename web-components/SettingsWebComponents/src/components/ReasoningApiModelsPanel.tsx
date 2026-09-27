import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron'
import {
  notifyReasoningApiModelsReady,
  onReasoningApiModelsEvent,
  requestSaveApiKey,
  requestToggleMaster,
  requestToggleModel,
  requestToggleProvider,
  requestToggleProviderKeySource,
} from '../services/reasoningApiModelsBridge'
import type { ReasoningApiProviderSummary } from '../types'

interface StatusMessage {
  text: string
  isError: boolean
}

function applyLocalByok(providers: ReasoningApiProviderSummary[], pendingByokOn: Record<string, boolean>) {
  return providers.map((provider) => {
    if (!pendingByokOn[provider.id] || provider.usingOwnApiKey) return provider
    return { ...provider, usingOwnApiKey: true, models: provider.models.map((model) => ({ ...model, enabled: false })) }
  })
}

export function ReasoningApiModelsPanel() {
  const [hasLoaded, setHasLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [useApiModels, setUseApiModels] = useState(false)
  const [providers, setProviders] = useState<ReasoningApiProviderSummary[]>([])
  const [apiKeyInputs, setApiKeyInputs] = useState<Record<string, string>>({})
  const [keyMessages, setKeyMessages] = useState<Record<string, StatusMessage>>({})
  const [statusMessage, setStatusMessage] = useState<StatusMessage | null>(null)
  const [masterPending, setMasterPending] = useState<string | null>(null)
  const [pendingProviders, setPendingProviders] = useState<Record<string, string>>({})
  const [pendingKeySources, setPendingKeySources] = useState<Record<string, string>>({})
  const [pendingKeys, setPendingKeys] = useState<Record<string, string>>({})
  const [pendingModels, setPendingModels] = useState<Record<string, string>>({})
  const [expandedProviders, setExpandedProviders] = useState<Record<string, boolean>>({})
  const pendingByokOnRef = useRef<Record<string, boolean>>({})
  const masterPendingRef = useRef<string | null>(null)
  const pendingProvidersRef = useRef<Record<string, string>>({})
  const pendingKeySourcesRef = useRef<Record<string, string>>({})
  const pendingKeysRef = useRef<Record<string, string>>({})
  const pendingModelsRef = useRef<Record<string, string>>({})
  masterPendingRef.current = masterPending
  pendingProvidersRef.current = pendingProviders
  pendingKeySourcesRef.current = pendingKeySources
  pendingKeysRef.current = pendingKeys
  pendingModelsRef.current = pendingModels

  useEffect(() => {
    const unsubscribe = onReasoningApiModelsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setHasLoaded(true)
        setLoadError(null)
        setIsLoading(event.isLoading)
        setUseApiModels(event.useApiModels)
        event.providers.forEach((provider) => {
          if (provider.usingOwnApiKey && pendingByokOnRef.current[provider.id]) {
            const next = { ...pendingByokOnRef.current }
            delete next[provider.id]
            pendingByokOnRef.current = next
          }
        })
        setProviders(applyLocalByok(event.providers, pendingByokOnRef.current))
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult') handleIntentResult(event)
    })
    notifyReasoningApiModelsReady()
    return unsubscribe
  }, [])

  function handleIntentResult(event: { requestId: string; status: 'success' | 'error'; message?: string }) {
    if (event.requestId === masterPendingRef.current) {
      masterPendingRef.current = null
      setMasterPending(null)
      setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update API models.', isError: true } : null)
      return
    }
    const providerId = Object.keys(pendingProvidersRef.current).find((id) => pendingProvidersRef.current[id] === event.requestId)
    if (providerId) {
      const next = { ...pendingProvidersRef.current }
      delete next[providerId]
      pendingProvidersRef.current = next
      setPendingProviders(next)
      setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update the provider.', isError: true } : null)
      return
    }
    const keySourceId = Object.keys(pendingKeySourcesRef.current).find((id) => pendingKeySourcesRef.current[id] === event.requestId)
    if (keySourceId) {
      const next = { ...pendingKeySourcesRef.current }
      delete next[keySourceId]
      pendingKeySourcesRef.current = next
      setPendingKeySources(next)
      setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update the API key source.', isError: true } : null)
      return
    }
    const keyId = Object.keys(pendingKeysRef.current).find((id) => pendingKeysRef.current[id] === event.requestId)
    if (keyId) {
      const next = { ...pendingKeysRef.current }
      delete next[keyId]
      pendingKeysRef.current = next
      setPendingKeys(next)
      if (event.status === 'success') {
        setApiKeyInputs((current) => ({ ...current, [keyId]: '' }))
        setKeyMessages((current) => ({ ...current, [keyId]: { text: event.message ?? 'API key is valid and saved', isError: false } }))
        const byok = { ...pendingByokOnRef.current }
        delete byok[keyId]
        pendingByokOnRef.current = byok
      } else {
        setKeyMessages((current) => ({ ...current, [keyId]: { text: event.message ?? 'Failed to save API key.', isError: true } }))
      }
      return
    }
    const modelKey = Object.keys(pendingModelsRef.current).find((id) => pendingModelsRef.current[id] === event.requestId)
    if (!modelKey) return
    const next = { ...pendingModelsRef.current }
    delete next[modelKey]
    pendingModelsRef.current = next
    setPendingModels(next)
    setStatusMessage(event.status === 'error' ? { text: event.message ?? 'Failed to update the model.', isError: true } : null)
  }

  function handleToggleMaster(next: boolean) {
    if (masterPendingRef.current) return
    setStatusMessage(null)
    const id = requestToggleMaster(next)
    masterPendingRef.current = id
    setMasterPending(id)
    setUseApiModels(next)
  }

  function handleToggleProvider(providerId: string, next: boolean) {
    if (pendingProvidersRef.current[providerId]) return
    setStatusMessage(null)
    const id = requestToggleProvider(providerId, next)
    const nextMap = { ...pendingProvidersRef.current, [providerId]: id }
    pendingProvidersRef.current = nextMap
    setPendingProviders(nextMap)
    setProviders((current) => current.map((provider) => provider.id === providerId ? { ...provider, enabled: next } : provider))
  }

  function handleToggleKeySource(providerId: string, next: boolean) {
    if (pendingKeySourcesRef.current[providerId]) return
    setStatusMessage(null)
    if (next) {
      pendingByokOnRef.current = { ...pendingByokOnRef.current, [providerId]: true }
      setProviders((current) => current.map((provider) => (
        provider.id === providerId
          ? { ...provider, usingOwnApiKey: true, models: provider.models.map((model) => ({ ...model, enabled: false })) }
          : provider
      )))
      return
    }
    const pendingByok = { ...pendingByokOnRef.current }
    delete pendingByok[providerId]
    pendingByokOnRef.current = pendingByok
    const id = requestToggleProviderKeySource(providerId, false)
    const nextMap = { ...pendingKeySourcesRef.current, [providerId]: id }
    pendingKeySourcesRef.current = nextMap
    setPendingKeySources(nextMap)
    setProviders((current) => current.map((provider) => provider.id === providerId ? { ...provider, usingOwnApiKey: false } : provider))
  }

  function handleSaveKey(providerId: string) {
    const value = apiKeyInputs[providerId] ?? ''
    if (pendingKeysRef.current[providerId] || value.length === 0) return
    setKeyMessages((current) => {
      const next = { ...current }
      delete next[providerId]
      return next
    })
    const id = requestSaveApiKey(providerId, value)
    const nextMap = { ...pendingKeysRef.current, [providerId]: id }
    pendingKeysRef.current = nextMap
    setPendingKeys(nextMap)
  }

  function toggleProviderExpanded(providerId: string) {
    setExpandedProviders((current) => ({ ...current, [providerId]: !(current[providerId] ?? true) }))
  }

  function handleToggleModel(providerId: string, modelId: string, next: boolean) {
    const key = `${providerId}:${modelId}`
    if (pendingModelsRef.current[key]) return
    setStatusMessage(null)
    const id = requestToggleModel(providerId, modelId, next)
    const nextMap = { ...pendingModelsRef.current, [key]: id }
    pendingModelsRef.current = nextMap
    setPendingModels(nextMap)
    setProviders((current) => current.map((provider) => (
      provider.id === providerId
        ? { ...provider, models: provider.models.map((model) => model.id === modelId ? { ...model, enabled: next } : model) }
        : provider
    )))
  }

  if (!hasLoaded && !loadError) {
    return <p className="reasoning-api-models-status" role="status">Loading reasoning API models...</p>
  }

  if (loadError) {
    return (
      <div className="reasoning-api-models-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyReasoningApiModelsReady()}>Retry</button>
      </div>
    )
  }

  return (
    <div className="reasoning-api-models-panel">
      <Switch
        id="reasoning-api-models-master-toggle"
        checked={useApiModels}
        disabled={masterPending !== null}
        onChange={handleToggleMaster}
        label="Use API Models"
      />
      {useApiModels && (
        isLoading ? (
          <p className="reasoning-api-models-status" role="status">Loading reasoning API models...</p>
        ) : (
          providers.map((provider) => (
            <ProviderCard
              key={provider.id}
              provider={provider}
              isExpanded={expandedProviders[provider.id] ?? true}
              apiKeyInput={apiKeyInputs[provider.id] ?? ''}
              keyMessage={keyMessages[provider.id] ?? null}
              providerPending={pendingProviders[provider.id] !== undefined}
              keySourcePending={pendingKeySources[provider.id] !== undefined}
              keyPending={pendingKeys[provider.id] !== undefined}
              pendingModels={pendingModels}
              onToggleProvider={(next) => handleToggleProvider(provider.id, next)}
              onToggleExpand={() => toggleProviderExpanded(provider.id)}
              onToggleKeySource={(next) => handleToggleKeySource(provider.id, next)}
              onApiKeyChange={(value) => setApiKeyInputs((current) => ({ ...current, [provider.id]: value }))}
              onSaveKey={() => handleSaveKey(provider.id)}
              onToggleModel={(modelId, next) => handleToggleModel(provider.id, modelId, next)}
            />
          ))
        )
      )}
      {statusMessage && (
        <p className={statusMessage.isError ? 'reasoning-api-models-status-error' : 'reasoning-api-models-status-success'} role={statusMessage.isError ? 'alert' : 'status'}>
          {statusMessage.text}
        </p>
      )}
    </div>
  )
}

function ProviderCard({
  provider, isExpanded, apiKeyInput, keyMessage, providerPending, keySourcePending, keyPending, pendingModels,
  onToggleProvider, onToggleExpand, onToggleKeySource, onApiKeyChange, onSaveKey, onToggleModel,
}: {
  provider: ReasoningApiProviderSummary
  isExpanded: boolean
  apiKeyInput: string
  keyMessage: StatusMessage | null
  providerPending: boolean
  keySourcePending: boolean
  keyPending: boolean
  pendingModels: Record<string, string>
  onToggleProvider: (next: boolean) => void
  onToggleExpand: () => void
  onToggleKeySource: (next: boolean) => void
  onApiKeyChange: (value: string) => void
  onSaveKey: () => void
  onToggleModel: (modelId: string, next: boolean) => void
}) {
  const availableCount = provider.models.length
  const enabledCount = provider.models.filter((model) => model.enabled).length
  const bodyId = `reasoning-api-models-provider-body-${provider.id}`
  return (
    <div className="reasoning-api-models-provider">
      <div className="reasoning-api-models-provider-header">
        <button
          type="button"
          className="reasoning-api-models-provider-disclosure"
          aria-expanded={provider.enabled && isExpanded}
          aria-controls={provider.enabled ? bodyId : undefined}
          disabled={!provider.enabled}
          onClick={onToggleExpand}
        >
          <span className="reasoning-api-models-provider-chevron" aria-hidden="true">
            <ExecutionDisclosureChevron expanded={provider.enabled && isExpanded} color="var(--text-secondary)" />
          </span>
          <span className="reasoning-api-models-provider-name">{provider.name}</span>
        </button>
        <span className="reasoning-api-models-provider-counts">
          <span className="reasoning-api-models-provider-count">{availableCount} available</span>
          <span className="reasoning-api-models-provider-count">{enabledCount} enabled</span>
        </span>
        <Switch id={`reasoning-api-models-provider-toggle-${provider.id}`} checked={provider.enabled} disabled={providerPending} onChange={onToggleProvider} label="" ariaLabel={`Enable ${provider.name} provider`} />
      </div>
      {provider.enabled && (
        <div id={bodyId} className={isExpanded ? 'reasoning-api-models-provider-collapse reasoning-api-models-provider-collapse-expanded' : 'reasoning-api-models-provider-collapse'}>
        <div className="reasoning-api-models-provider-collapse-inner">
        <>
          <div className="reasoning-api-models-key-section">
            <Switch id={`reasoning-api-models-key-source-${provider.id}`} checked={provider.usingOwnApiKey} disabled={keySourcePending} onChange={onToggleKeySource} label={`Enable ${provider.name} Models`} />
            {provider.usingOwnApiKey ? (
              <>
                {provider.hasKey && (
                  <p className="reasoning-api-models-key-active">
                    {provider.id === 'openai'
                      ? 'Your OpenAI API key is active and ready to use. This is the same key used by transcription API models.'
                      : `Your ${provider.name} API key is active and ready to use.`}
                  </p>
                )}
                <div className="reasoning-api-models-key-row">
                  <input type="password" className="reasoning-api-models-key-input" value={apiKeyInput} disabled={keyPending} placeholder={provider.hasKey ? `Update ${provider.name} API Key` : `Enter ${provider.name} API Key`} onChange={(event) => onApiKeyChange(event.target.value)} />
                  <button type="button" className="secondary-button" disabled={keyPending || apiKeyInput.length === 0} onClick={onSaveKey}>
                    {keyPending ? 'Validating...' : provider.hasKey ? 'Update Key' : 'Save & Validate'}
                  </button>
                </div>
                {keyMessage && (
                  <p className={keyMessage.isError ? 'reasoning-api-models-status-error' : 'reasoning-api-models-status-success'} role={keyMessage.isError ? 'alert' : 'status'}>{keyMessage.text}</p>
                )}
              </>
            ) : (
              <p className="reasoning-api-models-key-required">{provider.name} models require your API key. Enable the toggle above and provide your API key to use {provider.name} models.</p>
            )}
          </div>
          <ul className="reasoning-api-models-list">
            {provider.models.map((model) => (
              <li key={model.id} className="reasoning-api-models-row">
                <div className="reasoning-api-models-row-text">
                  <span className="reasoning-api-models-row-name">
                    {model.name}
                    {model.supportsExtendedThinking && <span className="reasoning-api-models-thinking">Extended thinking</span>}
                  </span>
                  {model.description && <span className="reasoning-api-models-row-description">{model.description}</span>}
                  <div className="reasoning-api-models-row-capabilities">
                    {model.capabilities.map((capability) => (
                      <span key={capability} className="reasoning-api-models-capability-chip">{capability}</span>
                    ))}
                  </div>
                </div>
                <Switch id={`reasoning-api-models-toggle-${provider.id}-${model.id}`} checked={model.enabled} disabled={pendingModels[`${provider.id}:${model.id}`] !== undefined} onChange={(next) => onToggleModel(model.id, next)} label="" ariaLabel={`Enable ${model.name}`} />
              </li>
            ))}
          </ul>
        </>
        </div>
        </div>
      )}
    </div>
  )
}