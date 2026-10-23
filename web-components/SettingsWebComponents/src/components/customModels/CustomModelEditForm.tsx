import { useEffect, useState } from 'react'
import { Switch } from '@shared/Switch'
import TokenizedSelect from '@shared/TokenizedSelect'
import { requestFetchLocalGGUFMetadata, requestPickLocalFile, requestTestConnection, requestUpdateModel } from '../../services/customModelsBridge'
import { FormField, FormSection } from './FormField'
import { DEFAULT_FEATURES, SERVER_TYPE_HINT, SERVER_TYPE_OPTIONS, serverTypeFrom, type ServerType, type WizardFeature } from './types'
import type { CustomModelSummary } from '../../types'
import type { LatestBridgeEvent } from '../CustomModelsPanel'

const TOOL_CALL_FORMATS: { id: 'json_tool_call' | 'function_parameter_tags'; label: string }[] = [
  { id: 'json_tool_call', label: 'JSON <tool_call>' },
  { id: 'function_parameter_tags', label: 'Function/Parameter Tags' },
]

const API_HANDLER_OPTIONS = [
  { id: 'openai_compatible', label: 'OpenAI-Compatible' },
  { id: 'anthropic_compatible', label: 'Anthropic-Compatible' },
]

function EditModelIcon({ isLocal }: { isLocal: boolean }) {
  return isLocal
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h6" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2 2.2 3 5 3 8s-1 5.8-3 8M12 4c-2 2.2-3 5-3 8s1 5.8 3 8" /></svg>
}

function ConnectionTestIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.2 2.2 4.8-5" /></svg>
}

interface CustomModelEditFormProps {
  model: CustomModelSummary
  latestEvent: LatestBridgeEvent | null
  onDismiss: () => void
}

export function CustomModelEditForm({ model, latestEvent, onDismiss }: CustomModelEditFormProps) {
  const [displayName, setDisplayName] = useState(model.displayName)
  const [description, setDescription] = useState(model.description ?? '')
  const [handler, setHandler] = useState(model.handler)
  const [baseUrl, setBaseUrl] = useState(model.baseUrl ?? '')
  const [modelIdentifier, setModelIdentifier] = useState(model.modelIdentifier ?? '')
  const [serverType, setServerType] = useState<ServerType>(serverTypeFrom(model.serverType))
  const [modelPath, setModelPath] = useState(model.modelPath ?? '')
  const [downloadUrl, setDownloadUrl] = useState(model.downloadUrl ?? '')
  const [contextWindow, setContextWindow] = useState(String(model.contextWindow))
  const [maxOutputTokens, setMaxOutputTokens] = useState(String(model.maxOutputTokens))
  const [requiresAuth, setRequiresAuth] = useState(model.requiresAuth)
  const [apiKey, setApiKey] = useState('')
  const [features, setFeatures] = useState<WizardFeature[]>(
    DEFAULT_FEATURES.map((feature) => ({ ...feature, isEnabled: model.features.includes(feature.id) }))
  )
  const [useSlimToolRendering, setUseSlimToolRendering] = useState(model.toolRendering === 'slim_schema')
  const [toolCallFormat, setToolCallFormat] = useState<'json_tool_call' | 'function_parameter_tags'>(
    model.toolCallFormat === 'function_parameter_tags' ? 'function_parameter_tags' : 'json_tool_call'
  )

  const [pendingPickRequestId, setPendingPickRequestId] = useState<string | null>(null)
  const [fileValidationError, setFileValidationError] = useState<string | null>(null)
  const [isFetchingMetadata, setIsFetchingMetadata] = useState(false)
  const [pendingMetadataRequestId, setPendingMetadataRequestId] = useState<string | null>(null)

  const [isTestingConnection, setIsTestingConnection] = useState(false)
  const [pendingConnectionTestRequestId, setPendingConnectionTestRequestId] = useState<string | null>(null)
  const [connectionTestResult, setConnectionTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pendingSaveRequestId, setPendingSaveRequestId] = useState<string | null>(null)

  const isFunctionCallingEnabled = features.some((feature) => feature.id === 'function_calling' && feature.isEnabled)
  const isLocalFileSource = model.isLocal && !!model.modelPath
  const isHuggingFaceSource = model.isLocal && !!model.downloadUrl && !model.modelPath
  const handlerLabel = handler === 'openai_compatible'
    ? 'OpenAI-Compatible'
    : handler === 'anthropic_compatible'
      ? 'Anthropic-Compatible'
      : 'Local GGUF'

  useEffect(() => {
    if (!latestEvent) return
    const { event } = latestEvent

    if (event.type === 'localFilePicked' && event.requestId === pendingPickRequestId) {
      setPendingPickRequestId(null)
      setFileValidationError(null)
      setModelPath(event.path)
      setIsFetchingMetadata(true)
      setPendingMetadataRequestId(requestFetchLocalGGUFMetadata(event.path))
    } else if (event.type === 'localFilePickError' && event.requestId === pendingPickRequestId) {
      setPendingPickRequestId(null)
      setFileValidationError(event.message)
    } else if (event.type === 'ggufMetadataResult' && event.requestId === pendingMetadataRequestId) {
      setIsFetchingMetadata(false)
      setPendingMetadataRequestId(null)
      if (event.success && event.contextWindow) setContextWindow(String(event.contextWindow))
    } else if (event.type === 'connectionTestResult' && event.requestId === pendingConnectionTestRequestId) {
      setIsTestingConnection(false)
      setPendingConnectionTestRequestId(null)
      setConnectionTestResult({ success: event.success, message: event.message })
    } else if (event.type === 'intentResult' && event.requestId === pendingSaveRequestId) {
      setIsSaving(false)
      setPendingSaveRequestId(null)
      if (event.status === 'success') {
        onDismiss()
      } else {
        setSaveError(event.message ?? 'Failed to save changes.')
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestEvent])

  function handleBrowse() {
    setFileValidationError(null)
    const id = requestPickLocalFile()
    setPendingPickRequestId(id)
  }

  function handleTestConnection() {
    setIsTestingConnection(true)
    setConnectionTestResult(null)
    const id = requestTestConnection({ handler, baseUrl, modelIdentifier, apiKey: requiresAuth && apiKey ? apiKey : undefined })
    setPendingConnectionTestRequestId(id)
  }

  function toggleFeature(featureId: string) {
    setFeatures((current) => current.map((feature) => (feature.id === featureId ? { ...feature, isEnabled: !feature.isEnabled } : feature)))
  }

  function isValid(): boolean {
    const parsedContextWindow = Number(contextWindow)
    const parsedMaxOutputTokens = Number(maxOutputTokens)
    return displayName !== ''
      && Number.isInteger(parsedContextWindow)
      && parsedContextWindow > 0
      && Number.isInteger(parsedMaxOutputTokens)
      && parsedMaxOutputTokens > 0
  }

  function handleSave() {
    if (!isValid()) {
      setSaveError('Please fill in all required fields.')
      return
    }
    setSaveError(null)
    setIsSaving(true)
    const id = requestUpdateModel(model.modelId, {
      displayName, handler: !model.isLocal ? handler : undefined,
      baseUrl: !model.isLocal && baseUrl !== '' ? baseUrl : undefined,
      modelIdentifier: !model.isLocal && modelIdentifier !== '' ? modelIdentifier : undefined,
      modelPath: isLocalFileSource && modelPath !== '' ? modelPath : undefined,
      downloadUrl: isHuggingFaceSource && downloadUrl !== '' ? downloadUrl : undefined,
      contextWindow: Number(contextWindow) || 4096,
      maxOutputTokens: Number(maxOutputTokens) || 4096,
      requiresAuth: !model.isLocal ? requiresAuth : false,
      apiKey: !model.isLocal && requiresAuth && apiKey !== '' ? apiKey : undefined,
      features: features.filter((feature) => feature.isEnabled).map((feature) => feature.id),
      toolRendering: !model.isLocal && isFunctionCallingEnabled && useSlimToolRendering ? 'slim_schema' : undefined,
      toolCallFormat: !model.isLocal && isFunctionCallingEnabled ? toolCallFormat : undefined,
      serverType: !model.isLocal && handler === 'openai_compatible' ? serverType : undefined,
      description: description === '' ? undefined : description,
    })
    setPendingSaveRequestId(id)
  }

  return (
    <div className="custom-models-wizard" role="dialog" aria-label={`Edit ${model.displayName}`}>
      <div className="custom-models-wizard-header">
        <div className="custom-models-edit-header">
          <span className="custom-models-edit-header-icon"><EditModelIcon isLocal={model.isLocal} /></span>
          <div>
            <p className="custom-models-wizard-progress">Edit Custom Model</p>
            <p className="custom-models-edit-header-detail">{handlerLabel} · {model.isLocal ? 'local GGUF model' : 'remote API model'}</p>
          </div>
        </div>
      </div>

      <div className="custom-models-wizard-body">
        <FormSection title="Basic Information">
          <FormField label="Display Name">
            <input type="text" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
          </FormField>
          <FormField label="Model ID" hint="Cannot be changed after creation.">
            <input type="text" value={model.modelId} readOnly disabled />
          </FormField>
          <FormField label="Description (optional)">
            <input type="text" value={description} onChange={(event) => setDescription(event.target.value)} />
          </FormField>
        </FormSection>

        {!model.isLocal && (
          <FormSection title="API Endpoint">
            <FormField label="API Handler" hint="Choose the request format supported by this endpoint.">
              <TokenizedSelect
                value={handler}
                ariaLabel="API Handler"
                onValueChange={setHandler}
                options={API_HANDLER_OPTIONS.map((option) => ({ value: option.id, label: option.label }))}
              />
            </FormField>
            {handler === 'openai_compatible' && (
              <FormField label="Server Type" hint={SERVER_TYPE_HINT}>
                <TokenizedSelect
                  value={serverType}
                  ariaLabel="Server Type"
                  onValueChange={setServerType}
                  options={SERVER_TYPE_OPTIONS}
                />
              </FormField>
            )}
            <FormField label="Base URL">
              <input type="text" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} />
            </FormField>
            <FormField label="Model Identifier">
              <input type="text" value={modelIdentifier} onChange={(event) => setModelIdentifier(event.target.value)} />
            </FormField>
          </FormSection>
        )}

        {isLocalFileSource && (
          <FormSection title="Local File">
            <p className="custom-models-local-file-path">{modelPath || 'No file selected'}</p>
            <button type="button" className="custom-models-action-button" onClick={handleBrowse}>Choose a Different File...</button>
            {fileValidationError && <p className="custom-models-error-text" role="alert">{fileValidationError}</p>}
            {isFetchingMetadata && <p className="custom-models-status" role="status">Extracting model metadata...</p>}
          </FormSection>
        )}

        {isHuggingFaceSource && (
          <FormSection title="HuggingFace Source">
            <FormField label="Repository URL" hint="Changing this does not re-download the model automatically.">
              <input type="text" value={downloadUrl} onChange={(event) => setDownloadUrl(event.target.value)} />
            </FormField>
          </FormSection>
        )}

        <FormSection title="Context Limits">
          <FormField label="Context Window (tokens)">
            <input type="number" value={contextWindow} onChange={(event) => setContextWindow(event.target.value)} />
          </FormField>
          <FormField label="Max Output Tokens">
            <input type="number" value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(event.target.value)} />
          </FormField>
        </FormSection>

        {!model.isLocal && (
          <FormSection title="Authentication">
            <Switch id="custom-model-edit-requires-api-key" label="Requires API Key" checked={requiresAuth} onChange={setRequiresAuth} />
            {requiresAuth && (
              <FormField label="API Key" hint="Leave blank to keep the existing key.">
                <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} autoComplete="off" />
              </FormField>
            )}
          </FormSection>
        )}

        <FormSection title="Supported Features">
          {features
            .filter((feature) => feature.id === 'streaming' || feature.id === 'system_prompts' || (feature.id === 'function_calling' && !model.isLocal))
            .map((feature) => (
              <Switch
                key={feature.id}
                id={`custom-model-edit-feature-${feature.id}`}
                label={feature.name}
                checked={feature.isEnabled}
                onChange={() => toggleFeature(feature.id)}
              />
            ))}
        </FormSection>

        {!model.isLocal && isFunctionCallingEnabled && (
          <FormSection title="Tool Runtime">
            <Switch id="custom-model-edit-use-slim-tool-rendering" label="Use Slim Tool Schema" checked={useSlimToolRendering} onChange={setUseSlimToolRendering} />
            <FormField label="Text Tool-Call Format">
              <TokenizedSelect
                value={toolCallFormat}
                ariaLabel="Text Tool-Call Format"
                onValueChange={setToolCallFormat}
                options={TOOL_CALL_FORMATS.map((format) => ({ value: format.id, label: format.label }))}
              />
            </FormField>
          </FormSection>
        )}

        {!model.isLocal && (
          <div className="custom-models-connection-test">
            <button type="button" className="custom-models-action-button custom-models-test-connection-button" onClick={handleTestConnection} disabled={!baseUrl || !modelIdentifier || isTestingConnection}>
              <ConnectionTestIcon />
              {isTestingConnection ? 'Testing...' : 'Test Connection'}
            </button>
            {connectionTestResult && (
              <p className={connectionTestResult.success ? 'custom-models-connection-result custom-models-connection-result-success' : 'custom-models-connection-result custom-models-connection-result-error'}>
                {connectionTestResult.message}
              </p>
            )}
          </div>
        )}
      </div>

      {saveError && <p className="custom-models-error-text" role="alert">{saveError}</p>}

      <div className="custom-models-wizard-footer">
        <button type="button" className="custom-models-action-button" onClick={onDismiss} disabled={isSaving}>Cancel</button>
        <button type="button" className="custom-models-action-button custom-models-primary-button" onClick={handleSave} disabled={!isValid() || isSaving}>
          {isSaving ? 'Saving...' : 'Save Changes'}
        </button>
      </div>
    </div>
  )
}
