import { useEffect, useState } from 'react'
import {
  requestCreateModel,
  requestDownloadModel,
  requestFetchGGUFMetadata,
  requestFetchLocalGGUFMetadata,
  requestPickLocalFile,
  requestProbeHFRepo,
  requestTestConnection,
} from '../../services/customModelsBridge'
import type { HFModelMetadataSummary } from '../../types'
import { ModelTypeStep, type ApiHandlerType } from './wizardSteps/ModelTypeStep'
import { LocalSourceStep, type LocalSource } from './wizardSteps/LocalSourceStep'
import { HuggingFaceStep } from './wizardSteps/HuggingFaceStep'
import { LocalFileStep } from './wizardSteps/LocalFileStep'
import { DetailsStep } from './wizardSteps/DetailsStep'
import { DEFAULT_FEATURES, type HFFileOption, type WizardFeature } from './types'
import { generateModelId } from './generateModelId'
import type { LatestBridgeEvent } from '../CustomModelsPanel'

type WizardStep = 'modelType' | 'localSource' | 'huggingface' | 'localFile' | 'details'

const STEP_ORDER: WizardStep[] = ['modelType', 'localSource', 'huggingface', 'localFile', 'details']

function AddModelIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 8v8M8 12h8" /></svg>
}

interface CustomModelWizardProps {
  latestEvent: LatestBridgeEvent | null
  onDismiss: () => void
}

export function CustomModelWizard({ latestEvent, onDismiss }: CustomModelWizardProps) {
  const [step, setStep] = useState<WizardStep>('modelType')
  const [isLocal, setIsLocal] = useState(true)
  const [handlerType, setHandlerType] = useState<ApiHandlerType>('openai_compatible')
  const [localSource, setLocalSource] = useState<LocalSource>('huggingface')

  const [huggingFaceUrl, setHuggingFaceUrl] = useState('')
  const [probedRepoId, setProbedRepoId] = useState<string | null>(null)
  const [ggufFiles, setGgufFiles] = useState<HFFileOption[]>([])
  const [selectedHFFile, setSelectedHFFile] = useState<string | null>(null)
  const [hfModelMetadata, setHfModelMetadata] = useState<HFModelMetadataSummary | null>(null)
  const [isProbing, setIsProbing] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)
  const [pendingProbeRequestId, setPendingProbeRequestId] = useState<string | null>(null)

  const [localFilePath, setLocalFilePath] = useState('')
  const [fileValidationError, setFileValidationError] = useState<string | null>(null)
  const [pendingPickRequestId, setPendingPickRequestId] = useState<string | null>(null)

  const [isFetchingMetadata, setIsFetchingMetadata] = useState(false)
  const [metadataError, setMetadataError] = useState<string | null>(null)
  const [pendingMetadataRequestId, setPendingMetadataRequestId] = useState<string | null>(null)
  const [extractedModelName, setExtractedModelName] = useState<string | null>(null)
  const [extractedArchitecture, setExtractedArchitecture] = useState<string | null>(null)
  const [extractedContextWindow, setExtractedContextWindow] = useState<number | null>(null)
  const [fileSize, setFileSize] = useState<number | null>(null)
  const [fileSizeHuman, setFileSizeHuman] = useState<string | null>(null)

  const [displayName, setDisplayName] = useState('')
  const [modelId, setModelId] = useState('')
  const [hasManuallyEditedModelId, setHasManuallyEditedModelId] = useState(false)
  const [description, setDescription] = useState('')
  const [contextWindow, setContextWindow] = useState('4096')
  const [maxOutputTokens, setMaxOutputTokens] = useState('2048')
  const [requiresAuth, setRequiresAuth] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [modelIdentifier, setModelIdentifier] = useState('')
  const [features, setFeatures] = useState<WizardFeature[]>(DEFAULT_FEATURES)

  const [isTestingConnection, setIsTestingConnection] = useState(false)
  const [pendingConnectionTestRequestId, setPendingConnectionTestRequestId] = useState<string | null>(null)
  const [connectionTestResult, setConnectionTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pendingCreateRequestId, setPendingCreateRequestId] = useState<string | null>(null)
  const [isDownloading, setIsDownloading] = useState(false)
  const [pendingDownloadRequestId, setPendingDownloadRequestId] = useState<string | null>(null)
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null)
  const [downloadStatus, setDownloadStatus] = useState<string | null>(null)
  const [downloadedModelId, setDownloadedModelId] = useState<string | null>(null)

  function applyExtractedMetadata(name: string | null, ctx: number | null) {
    if (name && displayName === '') {
      setDisplayName(name)
      if (modelId === '') setModelId(generateModelId(name))
    }
    if (ctx !== null) {
      setContextWindow(String(ctx))
      setMaxOutputTokens(String(Math.min(4096, Math.floor(ctx / 2))))
    }
  }

  function handleDetailsChange(partial: {
    displayName?: string; modelId?: string; description?: string; contextWindow?: string;
    maxOutputTokens?: string; requiresAuth?: boolean; apiKey?: string; baseUrl?: string; modelIdentifier?: string;
  }) {
    if (partial.displayName !== undefined) {
      setDisplayName(partial.displayName)
      if (!hasManuallyEditedModelId) setModelId(generateModelId(partial.displayName))
      return
    }
    if (partial.modelId !== undefined) {
      setModelId(partial.modelId)
      if (partial.modelId !== '' && partial.modelId !== generateModelId(displayName)) setHasManuallyEditedModelId(true)
      return
    }
    if (partial.description !== undefined) setDescription(partial.description)
    if (partial.contextWindow !== undefined) setContextWindow(partial.contextWindow)
    if (partial.maxOutputTokens !== undefined) setMaxOutputTokens(partial.maxOutputTokens)
    if (partial.requiresAuth !== undefined) setRequiresAuth(partial.requiresAuth)
    if (partial.apiKey !== undefined) setApiKey(partial.apiKey)
    if (partial.baseUrl !== undefined) setBaseUrl(partial.baseUrl)
    if (partial.modelIdentifier !== undefined) setModelIdentifier(partial.modelIdentifier)
  }

  function toggleFeature(featureId: string) {
    setFeatures((current) => current.map((feature) => (feature.id === featureId ? { ...feature, isEnabled: !feature.isEnabled } : feature)))
  }

  useEffect(() => {
    if (!latestEvent) return
    const { event } = latestEvent

    if (event.type === 'hfProbeResult' && event.requestId === pendingProbeRequestId) {
      setIsProbing(false)
      setPendingProbeRequestId(null)
      if (event.error) {
        setProbeError(event.error)
        setGgufFiles([])
        setProbedRepoId(null)
      } else {
        setProbeError(null)
        setGgufFiles(event.ggufFiles)
        setHfModelMetadata(event.modelMetadata)
        setSelectedHFFile(null)
        setProbedRepoId(event.repoId)
      }
    } else if (event.type === 'ggufMetadataResult' && event.requestId === pendingMetadataRequestId) {
      setIsFetchingMetadata(false)
      setPendingMetadataRequestId(null)
      if (event.success) {
        setMetadataError(null)
        setExtractedContextWindow(event.contextWindow)
        setExtractedArchitecture(event.architecture)
        setExtractedModelName(event.modelName)
        applyExtractedMetadata(event.modelName, event.contextWindow)
        setStep('details')
      } else {
        setMetadataError(event.error ?? 'Could not extract metadata.')
      }
    } else if (event.type === 'localFilePicked' && event.requestId === pendingPickRequestId) {
      setPendingPickRequestId(null)
      setFileValidationError(null)
      setLocalFilePath(event.path)
      setIsFetchingMetadata(true)
      const metadataRequestId = requestFetchLocalGGUFMetadata(event.path)
      setPendingMetadataRequestId(metadataRequestId)
    } else if (event.type === 'localFilePickError' && event.requestId === pendingPickRequestId) {
      setPendingPickRequestId(null)
      setLocalFilePath('')
      setFileValidationError(event.message)
    } else if (event.type === 'connectionTestResult' && event.requestId === pendingConnectionTestRequestId) {
      setIsTestingConnection(false)
      setPendingConnectionTestRequestId(null)
      setConnectionTestResult({ success: event.success, message: event.message })
    } else if (event.type === 'downloadProgress' && event.modelId === downloadedModelId) {
      setDownloadProgress(event.progress)
      setDownloadStatus(event.status)
    } else if (event.type === 'intentResult' && event.requestId === pendingCreateRequestId) {
      handleCreateResult(event.status === 'success', event.message ?? null)
    } else if (event.type === 'intentResult' && event.requestId === pendingDownloadRequestId) {
      handleDownloadResult(event.status === 'success', event.message ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [latestEvent])

  function handleSelectLocal() {
    setIsLocal(true)
    setStep('localSource')
  }

  function handleSelectApi(selectedHandlerType: ApiHandlerType) {
    setIsLocal(false)
    setHandlerType(selectedHandlerType)
    setStep('details')
  }

  function handleSelectLocalSource(source: LocalSource) {
    setLocalSource(source)
    setStep(source === 'huggingface' ? 'huggingface' : 'localFile')
  }

  function handleProbeRepo() {
    setIsProbing(true)
    setProbeError(null)
    setGgufFiles([])
    setProbedRepoId(null)
    const id = requestProbeHFRepo(huggingFaceUrl.trim())
    setPendingProbeRequestId(id)
  }

  function handleSelectHFFile(filename: string) {
    setSelectedHFFile(filename)
    const selectedFile = ggufFiles.find((file) => file.name === filename)
    setFileSize(selectedFile?.sizeBytes ?? null)
    setFileSizeHuman(selectedFile?.sizeHuman ?? null)
    if (!probedRepoId) return
    setIsFetchingMetadata(true)
    setMetadataError(null)
    const id = requestFetchGGUFMetadata(probedRepoId, filename)
    setPendingMetadataRequestId(id)
  }

  function handleBrowseForFile() {
    setFileValidationError(null)
    const id = requestPickLocalFile()
    setPendingPickRequestId(id)
  }

  function handleTestConnection() {
    setIsTestingConnection(true)
    setConnectionTestResult(null)
    const id = requestTestConnection({
      handler: handlerType, baseUrl, modelIdentifier,
      apiKey: requiresAuth && apiKey ? apiKey : undefined,
    })
    setPendingConnectionTestRequestId(id)
  }

  function isValid(): boolean {
    const parsedContextWindow = Number(contextWindow)
    const parsedMaxOutputTokens = Number(maxOutputTokens)
    if (
      displayName === ''
      || modelId === ''
      || !Number.isInteger(parsedContextWindow)
      || parsedContextWindow <= 0
      || !Number.isInteger(parsedMaxOutputTokens)
      || parsedMaxOutputTokens <= 0
    ) return false
    if (isLocal) {
      return localSource === 'huggingface' ? huggingFaceUrl !== '' && selectedHFFile !== null : localFilePath !== ''
    }
    return baseUrl !== '' && modelIdentifier !== ''
  }

  function selectedHuggingFaceDownloadUrl(): string | undefined {
    if (!probedRepoId || !selectedHFFile) return undefined
    return `https://huggingface.co/${probedRepoId}/resolve/main/${selectedHFFile}`
  }

  function handleSave() {
    if (!isValid()) {
      setSaveError('Please fill in all required fields.')
      return
    }
    setSaveError(null)
    setIsSaving(true)
    const id = requestCreateModel({
      modelId, displayName, handler: isLocal ? 'llama_cpp' : handlerType,
      baseUrl: isLocal ? undefined : baseUrl,
      modelIdentifier: isLocal ? undefined : modelIdentifier,
      modelPath: isLocal && localSource === 'local_file' ? localFilePath : undefined,
      downloadUrl: isLocal && localSource === 'huggingface' ? selectedHuggingFaceDownloadUrl() : undefined,
      contextWindow: Number(contextWindow), maxOutputTokens: Number(maxOutputTokens),
      requiresAuth: isLocal ? false : requiresAuth,
      apiKey: !isLocal && requiresAuth && apiKey !== '' ? apiKey : undefined,
      features: features.filter((feature) => feature.isEnabled).map((feature) => feature.id),
      description: description === '' ? undefined : description,
      fileSize: fileSize ?? undefined, fileSizeHuman: fileSizeHuman ?? undefined,
    })
    setPendingCreateRequestId(id)
  }

  function handleCreateResult(success: boolean, message: string | null) {
    setPendingCreateRequestId(null)
    if (!success) {
      setIsSaving(false)
      setSaveError(message ?? 'Failed to save model.')
      return
    }
    if (isLocal && localSource === 'huggingface' && selectedHFFile) {
      setIsDownloading(true)
      setDownloadedModelId(modelId)
      setDownloadProgress(0)
      setDownloadStatus('downloading')
      const id = requestDownloadModel(modelId, selectedHFFile)
      setPendingDownloadRequestId(id)
      return
    }
    setIsSaving(false)
    onDismiss()
  }

  function handleDownloadResult(success: boolean, message: string | null) {
    setPendingDownloadRequestId(null)
    setIsDownloading(false)
    setIsSaving(false)
    if (success) {
      onDismiss()
    } else {
      setSaveError(`Model was created but download failed: ${message ?? 'Unknown error'}. You can retry the download from the model list.`)
    }
  }

  function canGoBack(): boolean {
    return step !== 'modelType'
  }

  function handleGoBack() {
    if (step === 'localSource') setStep('modelType')
    else if (step === 'huggingface' || step === 'localFile') setStep('localSource')
    else if (step === 'details') setStep(isLocal ? (localSource === 'huggingface' ? 'huggingface' : 'localFile') : 'modelType')
  }

  const stepTitles: Record<WizardStep, string> = {
    modelType: 'Model Type', localSource: 'Model Source', huggingface: 'HuggingFace Repository',
    localFile: 'Local File', details: 'Model Details',
  }
  const activeStepPath: WizardStep[] = isLocal
    ? ['modelType', 'localSource', localSource === 'huggingface' ? 'huggingface' : 'localFile', 'details']
    : ['modelType', 'details']
  const stepIndex = activeStepPath.indexOf(step)
  const progressPercent = ((stepIndex + 1) / activeStepPath.length) * 100
  const isBusy = isProbing || isFetchingMetadata || isSaving || isDownloading

  return (
    <div className="custom-models-wizard" role="dialog" aria-modal="true" aria-label="Add Custom Model">
      <div className="custom-models-wizard-header">
        <div className="custom-models-wizard-header-content">
          <span className="custom-models-wizard-header-icon"><AddModelIcon /></span>
          <div>
            <p className="custom-models-wizard-progress">Add Custom Model</p>
            <p className="custom-models-wizard-step-detail">Step {stepIndex + 1} of {activeStepPath.length} · {stepTitles[step]}</p>
          </div>
        </div>
        <div className="custom-models-wizard-progress-track" role="progressbar" aria-label="Wizard progress" aria-valuemin={1} aria-valuemax={activeStepPath.length} aria-valuenow={stepIndex + 1}>
          <span style={{ width: `${progressPercent}%` }} />
        </div>
      </div>

      <div className="custom-models-wizard-body">
        {step === 'modelType' && (
          <ModelTypeStep isLocal={isLocal} handlerType={handlerType} onSelectLocal={handleSelectLocal} onSelectApi={handleSelectApi} />
        )}
        {step === 'localSource' && <LocalSourceStep localSource={localSource} onSelect={handleSelectLocalSource} />}
        {step === 'huggingface' && (
          <HuggingFaceStep
            url={huggingFaceUrl} onUrlChange={setHuggingFaceUrl} onProbe={handleProbeRepo} isProbing={isProbing}
            probeError={probeError} ggufFiles={ggufFiles} modelMetadata={hfModelMetadata}
            selectedFile={selectedHFFile} onSelectFile={handleSelectHFFile}
            isFetchingMetadata={isFetchingMetadata} metadataError={metadataError}
          />
        )}
        {step === 'localFile' && (
          <LocalFileStep
            filePath={localFilePath} onBrowse={handleBrowseForFile} fileValidationError={fileValidationError}
            isFetchingMetadata={isFetchingMetadata} metadataError={metadataError}
            extractedModelName={extractedModelName} extractedArchitecture={extractedArchitecture}
            extractedContextWindow={extractedContextWindow}
          />
        )}
        {step === 'details' && (
          <DetailsStep
            isLocal={isLocal}
            values={{ displayName, modelId, description, contextWindow, maxOutputTokens, requiresAuth, apiKey, baseUrl, modelIdentifier, features }}
            onChange={handleDetailsChange}
            onToggleFeature={toggleFeature}
            canTestConnection={baseUrl !== '' && modelIdentifier !== ''}
            onTestConnection={handleTestConnection}
            isTestingConnection={isTestingConnection}
            connectionTestResult={connectionTestResult}
            isDownloading={isDownloading}
            downloadProgress={downloadProgress}
            downloadStatus={downloadStatus}
          />
        )}
      </div>

      {saveError && <p className="custom-models-error-text" role="alert">{saveError}</p>}

      <div className="custom-models-wizard-footer">
        <div>
          {canGoBack() && (
            <button type="button" className="custom-models-action-button" onClick={handleGoBack} disabled={isBusy}>
              Back
            </button>
          )}
        </div>
        <div className="custom-models-wizard-footer-actions">
          <button type="button" className="custom-models-action-button" onClick={onDismiss} disabled={isSaving || isDownloading}>
            Cancel
          </button>
          {step === 'details' && (
            <button type="button" className="custom-models-action-button custom-models-primary-button" onClick={handleSave} disabled={!isValid() || isSaving || isDownloading}>
              {isSaving ? 'Saving...' : 'Add Model'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
