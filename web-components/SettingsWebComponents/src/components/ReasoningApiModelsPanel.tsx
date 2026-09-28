import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron'
import {
  notifyReasoningApiModelsReady,
  onReasoningApiModelsEvent,
  requestRemoveApiKey,
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

const PROVIDER_KEY_HELP_URLS: Record<string, string> = {
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
  gemini: 'https://aistudio.google.com/apikey',
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
  const [pendingKeyRemovals, setPendingKeyRemovals] = useState<Record<string, string>>({})
  const [confirmingKeyRemovals, setConfirmingKeyRemovals] = useState<Record<string, boolean>>({})
  const [expandedProviders, setExpandedProviders] = useState<Record<string, boolean>>({})
  const pendingByokOnRef = useRef<Record<string, boolean>>({})
  const masterPendingRef = useRef<string | null>(null)
  const pendingProvidersRef = useRef<Record<string, string>>({})
  const pendingKeySourcesRef = useRef<Record<string, string>>({})
  const pendingKeysRef = useRef<Record<string, string>>({})
  const pendingModelsRef = useRef<Record<string, string>>({})
  const pendingKeyRemovalsRef = useRef<Record<string, string>>({})
  masterPendingRef.current = masterPending
  pendingProvidersRef.current = pendingProviders
  pendingKeySourcesRef.current = pendingKeySources
  pendingKeysRef.current = pendingKeys
  pendingModelsRef.current = pendingModels
  pendingKeyRemovalsRef.current = pendingKeyRemovals

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
    const removalId = Object.keys(pendingKeyRemovalsRef.current).find((id) => pendingKeyRemovalsRef.current[id] === event.requestId)
    if (removalId) {
      const next = { ...pendingKeyRemovalsRef.current }
      delete next[removalId]
      pendingKeyRemovalsRef.current = next
      setPendingKeyRemovals(next)
      setConfirmingKeyRemovals((current) => ({ ...current, [removalId]: false }))
      setKeyMessages((current) => ({
        ...current,
        [removalId]: event.status === 'success'
          ? { text: 'Your API key was removed from this Mac.', isError: false }
          : { text: event.message ?? 'Failed to remove the API key.', isError: true },
      }))
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
    const provider = providers.find((candidate) => candidate.id === providerId)

    if (next && !provider?.hasKey) {
      // No saved key yet: just reveal the entry form. Saving a key below will
      // confirm this switch to "own key" with the backend once it validates.
      pendingByokOnRef.current = { ...pendingByokOnRef.current, [providerId]: true }
      setProviders((current) => current.map((candidate) => (
        candidate.id === providerId
          ? { ...candidate, usingOwnApiKey: true, models: candidate.models.map((model) => ({ ...model, enabled: false })) }
          : candidate
      )))
      return
    }

    const pendingByok = { ...pendingByokOnRef.current }
    delete pendingByok[providerId]
    pendingByokOnRef.current = pendingByok
    const id = requestToggleProviderKeySource(providerId, next)
    const nextMap = { ...pendingKeySourcesRef.current, [providerId]: id }
    pendingKeySourcesRef.current = nextMap
    setPendingKeySources(nextMap)
    setProviders((current) => current.map((candidate) => (
      candidate.id === providerId ? { ...candidate, usingOwnApiKey: next } : candidate
    )))
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

  function setKeyRemovalConfirming(providerId: string, confirming: boolean) {
    if (pendingKeyRemovalsRef.current[providerId]) return
    setKeyMessages((current) => {
      const next = { ...current }
      delete next[providerId]
      return next
    })
    setConfirmingKeyRemovals((current) => ({ ...current, [providerId]: confirming }))
  }

  function handleRemoveKey(providerId: string) {
    if (pendingKeyRemovalsRef.current[providerId]) return
    setStatusMessage(null)
    const id = requestRemoveApiKey(providerId)
    const nextMap = { ...pendingKeyRemovalsRef.current, [providerId]: id }
    pendingKeyRemovalsRef.current = nextMap
    setPendingKeyRemovals(nextMap)
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
              keyRemovalPending={pendingKeyRemovals[provider.id] !== undefined}
              isConfirmingKeyRemoval={confirmingKeyRemovals[provider.id] ?? false}
              pendingModels={pendingModels}
              onToggleProvider={(next) => handleToggleProvider(provider.id, next)}
              onToggleExpand={() => toggleProviderExpanded(provider.id)}
              onToggleKeySource={(next) => handleToggleKeySource(provider.id, next)}
              onApiKeyChange={(value) => setApiKeyInputs((current) => ({ ...current, [provider.id]: value }))}
              onSaveKey={() => handleSaveKey(provider.id)}
              onBeginRemoveKey={() => setKeyRemovalConfirming(provider.id, true)}
              onCancelRemoveKey={() => setKeyRemovalConfirming(provider.id, false)}
              onConfirmRemoveKey={() => handleRemoveKey(provider.id)}
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
  provider, isExpanded, apiKeyInput, keyMessage, providerPending, keySourcePending, keyPending, keyRemovalPending,
  isConfirmingKeyRemoval, pendingModels, onToggleProvider, onToggleExpand, onToggleKeySource, onApiKeyChange, onSaveKey,
  onBeginRemoveKey, onCancelRemoveKey, onConfirmRemoveKey, onToggleModel,
}: {
  provider: ReasoningApiProviderSummary
  isExpanded: boolean
  apiKeyInput: string
  keyMessage: StatusMessage | null
  providerPending: boolean
  keySourcePending: boolean
  keyPending: boolean
  keyRemovalPending: boolean
  isConfirmingKeyRemoval: boolean
  pendingModels: Record<string, string>
  onToggleProvider: (next: boolean) => void
  onToggleExpand: () => void
  onToggleKeySource: (next: boolean) => void
  onApiKeyChange: (value: string) => void
  onSaveKey: () => void
  onBeginRemoveKey: () => void
  onCancelRemoveKey: () => void
  onConfirmRemoveKey: () => void
  onToggleModel: (modelId: string, next: boolean) => void
}) {
  const keyControlsBusy = keyPending || keySourcePending || keyRemovalPending
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
            <Switch id={`reasoning-api-models-key-source-${provider.id}`} checked={provider.usingOwnApiKey} disabled={keySourcePending || keyRemovalPending} onChange={onToggleKeySource} label={`Use your ${provider.name} API key`} />
            <p className="reasoning-api-models-key-explainer">
              Turn this on if you already have your own {provider.name} API key and want to use it directly instead of
              Basil's built-in access.{' '}
              {PROVIDER_KEY_HELP_URLS[provider.id] && (
                <a href={PROVIDER_KEY_HELP_URLS[provider.id]} target="_blank" rel="noreferrer">
                  Get your {provider.name} API key
                </a>
              )}
            </p>
            {provider.usingOwnApiKey ? (
              <>
                {provider.hasKey && !isConfirmingKeyRemoval && (
                  <div className="reasoning-api-models-key-status-row">
                    <p className="reasoning-api-models-key-active">
                      {provider.id === 'openai'
                        ? 'Your OpenAI API key is active and ready to use. This is the same key used by transcription API models.'
                        : `Your ${provider.name} API key is active and ready to use.`}
                    </p>
                    <button type="button" className="reasoning-api-models-key-remove-button" disabled={keyControlsBusy} onClick={onBeginRemoveKey}>
                      Remove Key
                    </button>
                  </div>
                )}
                {provider.hasKey && isConfirmingKeyRemoval ? (
                  <div className="reasoning-api-models-key-remove-confirm" role="group" aria-label={`Remove ${provider.name} API key?`}>
                    <p className="reasoning-api-models-key-remove-confirm-title">Remove your {provider.name} API key?</p>
                    <p className="reasoning-api-models-key-remove-confirm-body">
                      This deletes the key from this Mac&rsquo;s keychain. {provider.name} models stop working until you add a key again.
                      {provider.id === 'openai' ? ' Transcription API models that use this key stop working too.' : ''}
                    </p>
                    <div className="reasoning-api-models-key-remove-confirm-actions">
                      <button type="button" className="secondary-button" disabled={keyRemovalPending} onClick={onCancelRemoveKey}>Cancel</button>
                      <button type="button" className="reasoning-api-models-key-remove-confirm-button" disabled={keyRemovalPending} onClick={onConfirmRemoveKey}>
                        {keyRemovalPending ? 'Removing...' : 'Remove Key'}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="reasoning-api-models-key-row">
                    <input type="password" className="reasoning-api-models-key-input" value={apiKeyInput} disabled={keyPending || keyRemovalPending} placeholder={provider.hasKey ? `Update ${provider.name} API Key` : `Enter ${provider.name} API Key`} onChange={(event) => onApiKeyChange(event.target.value)} />
                    <button type="button" className="secondary-button" disabled={keyPending || keyRemovalPending || apiKeyInput.length === 0} onClick={onSaveKey}>
                      {keyPending ? 'Validating...' : provider.hasKey ? 'Update Key' : 'Save & Validate'}
                    </button>
                  </div>
                )}
              </>
            ) : (
              <p className="reasoning-api-models-key-required">{provider.name} models require your API key. Turn on the option above and provide your API key to use {provider.name} models.</p>
            )}
            {keyMessage && (
              <p className={keyMessage.isError ? 'reasoning-api-models-status-error' : 'reasoning-api-models-status-success'} role={keyMessage.isError ? 'alert' : 'status'}>{keyMessage.text}</p>
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