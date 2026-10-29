import { useEffect, useRef, useState } from 'react'

import TokenizedSelect from '@shared/TokenizedSelect'

import { SetupStepActions } from '@/components/layout/SetupStepActions'
import { prefersReducedMotion } from '@/components/motion/prefersReducedMotion'
import { SmoothReveal } from './SmoothReveal'
import { BasilCloudAccountModal } from './BasilCloudAccountModal'
import { hasInteractionStyleSelection, IntroInteractionStyle } from './IntroInteractionStyle'

import {
  fetchInteractionStyleCatalog,
  fetchMemoryIntelligenceSettings,
  fetchLocalModelDownloadProgress,
  fetchModelAccessOptions,
  saveInteractionStyle,
  selectModelAccess,
  startLocalModelDownload,
  updateMemoryIntelligenceSettings,
} from '@/services/api'
import type { InteractionStyleGroup, InteractionStyleSelections } from '@/services/api'
import type {
  SetupAgentModelAccess,
  SetupAgentModelAccessMode,
  SetupAgentModelAccessOption,
} from '@/types'

interface Props {
  selectedModelAccess: SetupAgentModelAccess | null
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
  onContinue: (initialMessage: string, interactionStyle?: string[]) => void
}

type IntroStepName = 'model' | 'learning' | 'note'
type CaptureSettingsLoadState = 'loading' | 'ready' | 'unavailable'

const STEP_ORDER: readonly IntroStepName[] = ['model', 'learning', 'note'] as const
const STEP_TRANSITION_MS = 220

const modelChoices: Record<SetupAgentModelAccessMode, { title: string; detail: string }> = {
  local: {
    title: 'Local on this machine',
    detail: 'Private. Nothing leaves this machine.',
  },
  provider_key: {
    title: 'My own API key',
    detail: 'Use your own provider account.',
  },
  basil_cloud: {
    title: 'Basil Cloud',
    detail: 'Fastest, through your Basil account.',
  },
}

const providerLabels: Record<string, string> = {
  anthropic: 'Anthropic (Claude)',
  openai: 'OpenAI',
  google: 'Google (Gemini)',
}

const providerKeyHelpUrls: Record<string, string> = {
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
  google: 'https://aistudio.google.com/apikey',
}

export function IntroAndPrivacy({
  selectedModelAccess,
  onSelectModelAccess,
  onContinue,
}: Props) {
  const [freeformNote, setFreeformNote] = useState('')
  const [styleGroups, setStyleGroups] = useState<InteractionStyleGroup[]>([])
  const [styleSelections, setStyleSelections] = useState<InteractionStyleSelections>({})
  const [memoryAfterTaskEnabled, setMemoryAfterTaskEnabled] = useState(false)
  const [skillAfterTaskEnabled, setSkillAfterTaskEnabled] = useState(false)
  const [captureSettingsLoadState, setCaptureSettingsLoadState] = useState<CaptureSettingsLoadState>('loading')
  const [isContinuing, setIsContinuing] = useState(false)
  const [isConfirmingModelAccess, setIsConfirmingModelAccess] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const [currentStep, setCurrentStep] = useState<IntroStepName>('model')
  const [pendingStep, setPendingStep] = useState<IntroStepName | null>(null)
  const transitionTimerRef = useRef<number | null>(null)

  const stepIndex = STEP_ORDER.indexOf(currentStep)
  const isFinalStep = currentStep === 'note'
  const isTransitioning = pendingStep !== null
  const isModelAccessResolved = Boolean(selectedModelAccess?.resolved)

  useEffect(() => {
    let isCurrent = true
    void fetchMemoryIntelligenceSettings()
      .then((settings) => {
        if (!isCurrent) return
        setMemoryAfterTaskEnabled(settings.memory_after_task_enabled)
        setSkillAfterTaskEnabled(settings.skill_after_task_enabled)
        setCaptureSettingsLoadState('ready')
      })
      .catch(() => {
        if (isCurrent) setCaptureSettingsLoadState('unavailable')
      })
    return () => {
      isCurrent = false
    }
  }, [])

  useEffect(() => {
    let isCurrent = true
    // The style statements are optional, so a failed load just hides them and leaves the note.
    void fetchInteractionStyleCatalog()
      .then((groups) => { if (isCurrent) setStyleGroups(groups) })
      .catch(() => {})
    return () => {
      isCurrent = false
    }
  }, [])

  useEffect(() => () => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current)
    }
  }, [])

  const advanceTo = (nextStep: IntroStepName) => {
    if (isTransitioning || nextStep === currentStep) return
    setErrorMessage(null)
    if (prefersReducedMotion()) {
      setCurrentStep(nextStep)
      return
    }
    setPendingStep(nextStep)
    transitionTimerRef.current = window.setTimeout(() => {
      setCurrentStep(nextStep)
      setPendingStep(null)
      transitionTimerRef.current = null
    }, STEP_TRANSITION_MS)
  }

  const goNext = () => {
    if (currentStep === 'model' && (!isModelAccessResolved || isConfirmingModelAccess)) return
    if (isFinalStep) {
      void completeAndContinue()
      return
    }
    advanceTo(STEP_ORDER[stepIndex + 1])
  }

  const goBack = () => {
    if (stepIndex === 0) return
    advanceTo(STEP_ORDER[stepIndex - 1])
  }

  const completeAndContinue = async () => {
    if (isContinuing || captureSettingsLoadState === 'loading' || !isModelAccessResolved) return
    const finish = (interactionStyle: string[]) => (
      interactionStyle.length > 0
        ? onContinue(freeformNote.trim(), interactionStyle)
        : onContinue(freeformNote.trim())
    )

    setIsContinuing(true)
    setErrorMessage(null)
    try {
      if (captureSettingsLoadState !== 'unavailable') {
        await updateMemoryIntelligenceSettings({
          memory_after_task_enabled: memoryAfterTaskEnabled,
          skill_after_task_enabled: skillAfterTaskEnabled,
        })
      }
      const savedStyle = hasInteractionStyleSelection(styleSelections)
        ? await saveInteractionStyle(styleSelections)
        : null
      finish(savedStyle?.saved ? savedStyle.instructions : [])
    } catch (error) {
      setErrorMessage(error instanceof Error
        ? `I couldn't save those choices: ${error.message}`
        : "I couldn't save those choices.")
      setIsContinuing(false)
    }
  }

  const stepWrapperClass = `intro-step ${isTransitioning ? 'intro-step--leaving' : ''}`.trim()

  return (
    <section className="phase-section intro-privacy">
      <p className="eyebrow">Setup preferences · Step {stepIndex + 1} of {STEP_ORDER.length}</p>
      <h2>Let's shape how I work around how <em className="emphasis-you">you</em> work.</h2>

      <div className={stepWrapperClass} key={currentStep} aria-live="polite">
        {currentStep === 'model' && (
          <IntroModelStep
            selectedModelAccess={selectedModelAccess}
            onSelectModelAccess={onSelectModelAccess}
            onConfirmingChange={setIsConfirmingModelAccess}
          />
        )}
        {currentStep === 'learning' && (
          <IntroLearningStep
            memoryAfterTaskEnabled={memoryAfterTaskEnabled}
            skillAfterTaskEnabled={skillAfterTaskEnabled}
            captureSettingsLoadState={captureSettingsLoadState}
            onMemoryChange={setMemoryAfterTaskEnabled}
            onSkillChange={setSkillAfterTaskEnabled}
          />
        )}
        {currentStep === 'note' && (
          <IntroNoteStep
            freeformNote={freeformNote}
            onFreeformNoteChange={setFreeformNote}
            styleGroups={styleGroups}
            styleSelections={styleSelections}
            onStyleSelectionsChange={setStyleSelections}
          />
        )}
      </div>

      {errorMessage && (
        <p
          role="alert"
          style={{
            color: 'var(--error-base)',
            marginTop: 12,
          }}
        >
          {errorMessage}
        </p>
      )}

      <SetupStepActions>
        {/* Stays in the row on the first step so Continue does not shift when Back appears. */}
        <button
          type="button"
          className={`intro-step-back ${stepIndex === 0 ? 'intro-step-back--placeholder' : ''}`.trim()}
          onClick={goBack}
          disabled={stepIndex === 0 || isTransitioning || isContinuing}
          aria-hidden={stepIndex === 0 || undefined}
          tabIndex={stepIndex === 0 ? -1 : undefined}
        >
          ← Back
        </button>

        <div className="intro-step-dots" aria-hidden="true">
          {STEP_ORDER.map((step, index) => (
            <span
              key={step}
              className={`intro-step-dot ${
                index === stepIndex ? 'current' : index < stepIndex ? 'done' : ''
              }`}
            />
          ))}
        </div>

        <button
          type="button"
          className="primary-button intro-step-primary"
          onClick={goNext}
          disabled={
            isTransitioning
            || isContinuing
            || (currentStep === 'model' && (!isModelAccessResolved || isConfirmingModelAccess))
            || (currentStep === 'learning' && captureSettingsLoadState === 'loading')
          }
        >
          {currentStep === 'model' && !isModelAccessResolved
            ? (selectedModelAccess?.mode === 'provider_key'
              ? 'Validate your API key to continue'
              : 'Choose a confirmed reasoning route')
            : currentStep === 'learning' && captureSettingsLoadState === 'loading'
            ? 'Loading preferences…'
            : isFinalStep
            ? (isContinuing ? 'Saving…' : 'Continue to guided setup')
            : 'Continue'}
        </button>
      </SetupStepActions>
    </section>
  )
}

interface IntroModelStepProps {
  selectedModelAccess: SetupAgentModelAccess | null
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
  onConfirmingChange: (isConfirming: boolean) => void
}

type KeyValidationState = 'idle' | 'checking' | 'valid' | 'invalid'
type LocalDownloadPhase = 'idle' | 'starting' | 'downloading' | 'stopped'

export const LOCAL_DOWNLOAD_POLL_INTERVAL_MS = 1000
const ACTIVE_DOWNLOAD_STATUSES: readonly string[] = ['queued', 'downloading']

function IntroModelStep({
  selectedModelAccess,
  onSelectModelAccess,
  onConfirmingChange,
}: IntroModelStepProps) {
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'unavailable'>('loading')
  const [options, setOptions] = useState<SetupAgentModelAccessOption[]>([])
  const [pendingMode, setPendingMode] = useState<SetupAgentModelAccessMode | null>(null)
  const [provider, setProvider] = useState('anthropic')
  const [providerKey, setProviderKey] = useState('')
  const [isEnteringNewKey, setIsEnteringNewKey] = useState(false)
  const [keyValidation, setKeyValidation] = useState<KeyValidationState>('idle')
  const [keyValidationError, setKeyValidationError] = useState<string | null>(null)
  const [chosenModelId, setChosenModelId] = useState<string | null>(
    selectedModelAccess?.mode === 'provider_key' ? selectedModelAccess.model_id ?? null : null,
  )
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [isHelpOpen, setIsHelpOpen] = useState(false)
  const [downloadPhase, setDownloadPhase] = useState<LocalDownloadPhase>('idle')
  const [downloadPercent, setDownloadPercent] = useState(0)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const isMountedRef = useRef(true)
  const isWatchingDownloadRef = useRef(false)
  const awaitingCloudSelectionRef = useRef(false)
  const accountCheckedRef = useRef(false)
  const [isAccountModalOpen, setIsAccountModalOpen] = useState(false)
  const [isCheckingAccount, setIsCheckingAccount] = useState(false)

  const providerKeyOption = options.find(option => option.mode === 'provider_key')
  const cloudRouteOption = options.find(option => option.mode === 'basil_cloud')
  const accountDialogOption = cloudRouteOption && !cloudRouteOption.available
    && (cloudRouteOption.requires_sign_in || cloudRouteOption.requires_payment_method)
    ? cloudRouteOption
    : null
  const savedProvider = providerKeyOption && !providerKeyOption.requires_provider_key_input
    ? providerKeyOption.provider ?? null
    : null
  const isProviderKeySelected = selectedModelAccess?.mode === 'provider_key'
  const isKeyFormOpen = isProviderKeySelected && (!savedProvider || isEnteringNewKey)
  const activeProvider = savedProvider && !isEnteringNewKey ? savedProvider : provider
  const modelsFor = (providerId: string) => (providerKeyOption?.provider_models ?? []).filter(
    choice => choice.provider === providerId,
  )
  const modelFor = (providerId: string, modelId: string | null) => {
    const models = modelsFor(providerId)
    return models.find(choice => choice.model_id === modelId)
      ?? models.find(choice => choice.recommended)
      ?? models[0]
  }
  const activeProviderModels = modelsFor(activeProvider)
  const activeModel = modelFor(activeProvider, chosenModelId)

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
    }
  }, [])

  // Follows one local-model download until the backend stops reporting it as queued or downloading, then re-reads the options so disk state, not a status string, decides whether the route is usable.
  const watchLocalDownload = async (modelType: string, variant: string) => {
    if (isWatchingDownloadRef.current) return
    isWatchingDownloadRef.current = true
    setDownloadPhase('downloading')
    try {
      while (isMountedRef.current) {
        let status = ''
        try {
          const progress = await fetchLocalModelDownloadProgress(modelType, variant)
          status = progress.status
          if (isMountedRef.current && typeof progress.progress === 'number') {
            setDownloadPercent(Math.max(0, Math.min(100, Math.round(progress.progress * 100))))
          }
        } catch {
          break
        }
        if (!ACTIVE_DOWNLOAD_STATUSES.includes(status)) break
        await new Promise<void>(resolve => window.setTimeout(resolve, LOCAL_DOWNLOAD_POLL_INTERVAL_MS))
      }
      if (!isMountedRef.current) return
      const refreshed = await fetchModelAccessOptions(accountCheckedRef.current)
      if (!isMountedRef.current) return
      setOptions(refreshed.options)
      const refreshedLocal = refreshed.options.find(option => option.mode === 'local')
      if (refreshedLocal?.downloaded) {
        setDownloadPhase('idle')
        setDownloadPercent(0)
      } else {
        setDownloadPhase('stopped')
      }
    } catch {
      if (isMountedRef.current) setDownloadPhase('stopped')
    } finally {
      isWatchingDownloadRef.current = false
    }
  }

  useEffect(() => {
    let isCurrent = true
    void fetchModelAccessOptions()
      .then(response => {
        if (!isCurrent) return
        setOptions(response.options)
        setLoadState('ready')
        const providerOption = response.options.find(option => option.mode === 'provider_key')
        if (providerOption?.provider) {
          setProvider(providerOption.provider)
        }
        const localOption = response.options.find(option => option.mode === 'local')
        if (localOption?.downloaded === false && localOption.local_model_type && localOption.local_model_variant) {
          const { local_model_type: modelType, local_model_variant: variant } = localOption
          // A download started earlier in this launch keeps running; pick it back up instead of offering a second start.
          void fetchLocalModelDownloadProgress(modelType, variant)
            .then(progress => {
              if (isCurrent && ACTIVE_DOWNLOAD_STATUSES.includes(progress.status)) {
                void watchLocalDownload(modelType, variant)
              }
            })
            .catch(() => undefined)
        }
      })
      .catch(() => {
        if (isCurrent) setLoadState('unavailable')
      })
    return () => {
      isCurrent = false
    }
  }, [])

  // Reads the Basil account. Only reached once the user has chosen Basil Cloud (and by the account dialog afterward), because reading the account makes the app open its Keychain, which can show a macOS permission prompt.
  const refreshAccountOptions = async () => {
    awaitingCloudSelectionRef.current = true
    accountCheckedRef.current = true
    const refreshed = await fetchModelAccessOptions(true)
    if (!isMountedRef.current) return
    setOptions(refreshed.options)
  }

  // After the account has been read for someone who chose Basil Cloud: confirm the route when it is usable, otherwise open the dialog that signs them in or collects a payment method.
  useEffect(() => {
    if (!awaitingCloudSelectionRef.current) return
    const cloudOption = options.find(option => option.mode === 'basil_cloud')
    if (!cloudOption || cloudOption.requires_account_check) return
    if (cloudOption.available) {
      awaitingCloudSelectionRef.current = false
      setIsAccountModalOpen(false)
      void selectRoute(cloudOption)
    } else if (cloudOption.requires_sign_in || cloudOption.requires_payment_method) {
      setIsAccountModalOpen(true)
    }
  }, [options])

  const closeAccountModal = () => {
    awaitingCloudSelectionRef.current = false
    setIsAccountModalOpen(false)
  }

  const chooseBasilCloud = async (option: SetupAgentModelAccessOption) => {
    setErrorMessage(null)
    if (option.available && !option.requires_account_check) {
      await selectRoute(option)
      return
    }
    setIsCheckingAccount(true)
    try {
      await refreshAccountOptions()
    } catch (error) {
      setErrorMessage(errorText(error, 'I couldn’t check your Basil account. Please try again.'))
    } finally {
      if (isMountedRef.current) setIsCheckingAccount(false)
    }
  }

  useEffect(() => {
    onConfirmingChange(pendingMode !== null)
  }, [onConfirmingChange, pendingMode])

  useEffect(() => () => onConfirmingChange(false), [onConfirmingChange])

  const resetKeyValidation = () => {
    setKeyValidation('idle')
    setKeyValidationError(null)
  }

  const handleProviderChange = (nextProvider: string) => {
    setProvider(nextProvider)
    setChosenModelId(null)
    resetKeyValidation()
  }

  const handleKeyChange = (nextKey: string) => {
    setProviderKey(nextKey)
    resetKeyValidation()
  }

  const errorText = (error: unknown, fallback: string) => (
    error instanceof Error && error.message ? error.message : fallback
  )

  const startDownload = async (option: SetupAgentModelAccessOption) => {
    const modelType = option.local_model_type
    const variant = option.local_model_variant
    if (!modelType || !variant || downloadPhase === 'starting' || downloadPhase === 'downloading') return
    setDownloadError(null)
    setDownloadPercent(0)
    setDownloadPhase('starting')
    try {
      await startLocalModelDownload(modelType, variant)
    } catch (error) {
      setDownloadError(errorText(error, 'I couldn’t start that download. Please try again.'))
      setDownloadPhase('idle')
      return
    }
    await watchLocalDownload(modelType, variant)
  }

  const markProviderKeyPending = (providerId: string) => {
    onSelectModelAccess({ mode: 'provider_key', provider: providerId, resolved: false })
  }

  const confirmSavedProviderKey = async (modelId: string | undefined) => {
    if (!savedProvider || pendingMode) return
    setPendingMode('provider_key')
    setErrorMessage(null)
    try {
      const response = await selectModelAccess({ mode: 'provider_key', provider: savedProvider, model_id: modelId })
      onSelectModelAccess(response.access)
    } catch (error) {
      markProviderKeyPending(savedProvider)
      setErrorMessage(errorText(error, 'I couldn’t confirm your saved key. Please try again.'))
    } finally {
      setPendingMode(null)
    }
  }

  const confirmNewProviderKey = async () => {
    const trimmed = providerKey.trim()
    if (!trimmed || pendingMode) return
    setPendingMode('provider_key')
    setKeyValidation('checking')
    setKeyValidationError(null)
    setErrorMessage(null)
    try {
      const response = await selectModelAccess({
        mode: 'provider_key',
        provider,
        model_id: modelFor(provider, chosenModelId)?.model_id,
        provider_api_key: trimmed,
      })
      onSelectModelAccess(response.access)
      setOptions(current => current.map(option => (
        option.mode === 'provider_key'
          ? { ...option, provider, requires_provider_key_input: false }
          : option
      )))
      setProviderKey('')
      setIsEnteringNewKey(false)
      setKeyValidation('valid')
    } catch (error) {
      setKeyValidation('invalid')
      setKeyValidationError(errorText(error, 'That key was rejected by the provider.'))
    } finally {
      setPendingMode(null)
    }
  }

  const chooseRoute = async (option: SetupAgentModelAccessOption) => {
    if (pendingMode || isCheckingAccount) return
    if (option.mode === 'basil_cloud') {
      await chooseBasilCloud(option)
      return
    }
    if (!option.available) return
    awaitingCloudSelectionRef.current = false
    await selectRoute(option)
  }

  const selectRoute = async (option: SetupAgentModelAccessOption) => {
    if (option.mode === 'provider_key') {
      if (isProviderKeySelected) return
      setErrorMessage(null)
      if (savedProvider) {
        await confirmSavedProviderKey(modelFor(savedProvider, chosenModelId)?.model_id)
      } else {
        markProviderKeyPending(provider)
      }
      return
    }

    setPendingMode(option.mode)
    setErrorMessage(null)
    try {
      const response = await selectModelAccess({ mode: option.mode, local_model_id: option.local_model_id })
      onSelectModelAccess(response.access)
      setProviderKey('')
      setIsEnteringNewKey(false)
      resetKeyValidation()
    } catch (error) {
      setErrorMessage(errorText(error, 'I couldn’t confirm that reasoning route. Please try again.'))
    } finally {
      setPendingMode(null)
    }
  }

  const handleModelChange = (modelId: string) => {
    setChosenModelId(modelId)
    if (isProviderKeySelected && !isKeyFormOpen) void confirmSavedProviderKey(modelId)
  }

  const startEnteringNewKey = () => {
    setIsEnteringNewKey(true)
    setProviderKey('')
    resetKeyValidation()
    markProviderKeyPending(provider)
  }

  const cancelEnteringNewKey = () => {
    setIsEnteringNewKey(false)
    setProviderKey('')
    resetKeyValidation()
    if (savedProvider) void confirmSavedProviderKey(modelFor(savedProvider, chosenModelId)?.model_id)
  }

  return (
    <div className="intro-step-body">
      <h3>Reasoning during setup</h3>
      <p className="intro-step-lede">Pick how I should think during setup.</p>

      <SmoothReveal open={loadState === 'loading'} className="intro-step-reveal">
        <div className="intro-step-reveal-body">
          <p role="status">Checking available reasoning routes…</p>
        </div>
      </SmoothReveal>
      <SmoothReveal open={loadState === 'unavailable'} className="intro-step-reveal">
        <div className="intro-step-reveal-body">
          <p role="alert" style={{ color: 'var(--error-base)' }}>
            I couldn’t reach the setup service to check available reasoning routes.
          </p>
        </div>
      </SmoothReveal>
      <SmoothReveal open={loadState === 'ready'} className="intro-step-reveal">
        <div className="intro-step-reveal-body choice-list" role="group" aria-label="Setup reasoning preference">
          {options.map(option => {
            const choice = modelChoices[option.mode]
            const selected = selectedModelAccess?.mode === option.mode
            const isExpandedProviderKey = option.mode === 'provider_key' && isProviderKeySelected
            const hasSavedProviderKey = option.mode === 'provider_key' && Boolean(savedProvider)
            const opensAccountDialog = option.mode === 'basil_cloud' && !option.available
              && Boolean(option.requires_sign_in || option.requires_payment_method)
            return (
              <div key={option.mode} className="choice-option-wrapper">
                <button
                  type="button"
                  className={[
                    'choice-option',
                    `choice-option--${option.mode}`,
                    selected ? 'selected' : '',
                  ].join(' ')}
                  aria-pressed={selected}
                  disabled={
                    (!option.available && !opensAccountDialog) || pendingMode !== null || isCheckingAccount
                  }
                  onClick={() => void chooseRoute(option)}
                >
                  <div>
                    <strong>{choice.title}</strong>
                    <span>
                      {option.mode === 'basil_cloud' && isCheckingAccount
                        ? 'Checking your Basil account…'
                        : pendingMode === option.mode && !isKeyFormOpen ? 'Confirming…' : choice.detail}
                    </span>
                    {option.mode === 'local' && selected && option.display_name && (
                      <span className="choice-option-model-name">
                        Model: <strong>{option.display_name}</strong>
                      </span>
                    )}
                    <SmoothReveal open={hasSavedProviderKey && !isEnteringNewKey}>
                      <span className="choice-option-note choice-option-note--positive">
                        Your saved {providerLabels[option.provider ?? ''] ?? option.provider} key is already validated and ready to use.
                      </span>
                    </SmoothReveal>
                    {!option.available && option.unavailable_reason && (
                      <span className="choice-option-unavailable">{option.unavailable_reason}</span>
                    )}
                  </div>
                </button>
                {option.mode === 'local' && option.downloaded === false && option.local_model_type && option.local_model_variant && (
                  <div className="choice-option-reveal-body choice-option-download">
                    {downloadPhase === 'starting' || downloadPhase === 'downloading' ? (
                      <div className="choice-option-download-progress" role="status">
                        <span>
                          {downloadPhase === 'starting' ? 'Starting download…' : `Downloading… ${downloadPercent}%`}
                          {' '}You can keep going with another route while this finishes.
                        </span>
                        <div className="choice-option-download-bar" aria-hidden="true">
                          <div className="choice-option-download-bar-fill" style={{ width: `${downloadPercent}%` }} />
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={pendingMode !== null}
                        onClick={() => void startDownload(option)}
                      >
                        {`Download ${option.display_name ?? 'the local model'}${option.download_size_description ? ` (${option.download_size_description})` : ''}`}
                      </button>
                    )}
                    {downloadPhase === 'stopped' && (
                      <p className="choice-option-key-status choice-option-key-status--invalid" role="alert">
                        The download stopped before it finished. Try again.
                      </p>
                    )}
                    {downloadError && (
                      <p className="choice-option-key-status choice-option-key-status--invalid" role="alert">{downloadError}</p>
                    )}
                  </div>
                )}
                <SmoothReveal open={isExpandedProviderKey && hasSavedProviderKey && !isEnteringNewKey}>
                  <div className="choice-option-reveal-body">
                    <button
                      type="button"
                      className="choice-option-secondary-action"
                      disabled={pendingMode !== null}
                      onClick={startEnteringNewKey}
                    >
                      Use a different key instead
                    </button>
                  </div>
                </SmoothReveal>
                <SmoothReveal open={isExpandedProviderKey && isKeyFormOpen}>
                  <div className="choice-option-reveal-body choice-option-provider-key-form">
                    <div className="choice-option-provider-field">
                      <span>Provider</span>
                      <TokenizedSelect
                        value={provider}
                        options={Object.entries(providerLabels).map(([value, label]) => ({ value, label }))}
                        onValueChange={handleProviderChange}
                        disabled={pendingMode !== null}
                        ariaLabel="Provider"
                        className="choice-option-provider-select"
                      />
                    </div>
                    <label>
                      <span>API key</span>
                      <input
                        type="password"
                        value={providerKey}
                        onChange={event => handleKeyChange(event.target.value)}
                        onKeyDown={event => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            void confirmNewProviderKey()
                          }
                        }}
                        placeholder="API key"
                        autoComplete="off"
                        disabled={pendingMode !== null}
                      />
                    </label>
                    <div className="choice-option-key-validate-row">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={!providerKey.trim() || pendingMode !== null}
                        onClick={() => void confirmNewProviderKey()}
                      >
                        {keyValidation === 'checking' ? 'Checking…' : 'Validate & use key'}
                      </button>
                      <SmoothReveal open={keyValidation === 'valid' || keyValidation === 'invalid'}>
                        {keyValidation === 'valid' ? (
                          <span className="choice-option-key-status choice-option-key-status--valid" role="status">
                            ✓ Key confirmed with {providerLabels[provider]}
                          </span>
                        ) : (
                          <span className="choice-option-key-status choice-option-key-status--invalid" role="alert">
                            {keyValidationError ?? 'That key was rejected.'}
                          </span>
                        )}
                      </SmoothReveal>
                    </div>
                    <p className="choice-option-key-help">
                      Setup requests go straight to {providerLabels[provider]} using this key. Don't have one yet?{' '}
                      <a href={providerKeyHelpUrls[provider]} target="_blank" rel="noreferrer">
                        Get an API key from {providerLabels[provider]}
                      </a>
                      .
                    </p>
                    {isEnteringNewKey && (
                      <button
                        type="button"
                        className="choice-option-secondary-action"
                        disabled={pendingMode !== null}
                        onClick={cancelEnteringNewKey}
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </SmoothReveal>
                <SmoothReveal open={isExpandedProviderKey && Boolean(activeModel)}>
                  {activeModel && (
                    <div className="choice-option-reveal-body choice-option-model-picker">
                      <div className="choice-option-provider-field">
                        <span>Model</span>
                        <TokenizedSelect
                          value={activeModel.model_id}
                          options={activeProviderModels.map(choice => ({
                            value: choice.model_id,
                            label: choice.recommended ? `${choice.display_name} (Recommended)` : choice.display_name,
                          }))}
                          onValueChange={handleModelChange}
                          disabled={pendingMode !== null}
                          ariaLabel="Setup Assistant model"
                          className="choice-option-provider-select"
                        />
                      </div>
                      <p className="choice-option-model-note">
                        Setup Assistant will use <strong>{activeModel.display_name}</strong>
                        {activeModel.recommended ? ', a balanced choice for speed and quality' : ''}. This only applies to setup. Your default model in Settings → Models stays the same.
                      </p>
                    </div>
                  )}
                </SmoothReveal>
              </div>
            )
          })}
        </div>
      </SmoothReveal>

      <SmoothReveal open={Boolean(errorMessage)} className="intro-step-reveal">
        <div className="intro-step-reveal-body">
          <p role="alert" style={{ color: 'var(--error-base)', margin: 0 }}>{errorMessage}</p>
        </div>
      </SmoothReveal>

      <div className={`intro-help${isHelpOpen ? ' intro-help--open' : ''}`}>
        <button
          type="button"
          className="intro-help-summary"
          aria-expanded={isHelpOpen}
          aria-controls="intro-help-body"
          onClick={() => setIsHelpOpen(value => !value)}
        >
          <span>What's the difference?</span>
          <span className="intro-help-chevron" aria-hidden="true">›</span>
        </button>
        <SmoothReveal open={isHelpOpen}>
          <div className="intro-help-body" id="intro-help-body">
            <dl>
              <div>
                <dt>{modelChoices.local.title}</dt>
                <dd>
                  I reason here using a local model on your disk. Slower than the cloud option and I
                  use some memory while I'm thinking, but this setup conversation stays on this
                  machine.
                </dd>
              </div>
              <div>
                <dt>{modelChoices.basil_cloud.title}</dt>
                <dd>
                  I reason through a stronger model hosted by Basil Cloud. Faster and smarter, but
                  the contents of this conversation are routed through Basil Cloud while I am
                  working.
                </dd>
              </div>
              <div>
                <dt>{modelChoices.provider_key.title}</dt>
                <dd>I’ll send setup requests directly to the provider you choose using the API key you enter here.</dd>
              </div>
            </dl>
            <p className="intro-help-footnote">
              This only governs how I think during setup. It does not lock in how I reason later —
              you can change my main models any time in Settings.
            </p>
          </div>
        </SmoothReveal>
      </div>
      {isAccountModalOpen && accountDialogOption && (
        <BasilCloudAccountModal
          option={accountDialogOption}
          refreshOptions={refreshAccountOptions}
          onClose={closeAccountModal}
        />
      )}
    </div>
  )
}

interface IntroLearningStepProps {
  memoryAfterTaskEnabled: boolean
  skillAfterTaskEnabled: boolean
  captureSettingsLoadState: CaptureSettingsLoadState
  onMemoryChange: (value: boolean) => void
  onSkillChange: (value: boolean) => void
}

function IntroLearningStep({
  memoryAfterTaskEnabled,
  skillAfterTaskEnabled,
  captureSettingsLoadState,
  onMemoryChange,
  onSkillChange,
}: IntroLearningStepProps) {
  const settingsUnavailable = captureSettingsLoadState === 'unavailable'

  return (
    <div className="intro-step-body">
      <h3>Learning from your work</h3>
      <p className="intro-step-lede">
        {captureSettingsLoadState === 'loading'
          ? 'Checking your saved learning preferences…'
          : settingsUnavailable
            ? 'I couldn’t read your saved learning preferences, so continuing will leave them unchanged.'
            : 'Both are optional, and nothing is saved without your approval.'}
      </p>

      <fieldset className="intro-capture-toggles" aria-label="Optional learning preferences">
        <div className="intro-capture-toggle intro-capture-toggle--memory">
          <span className="intro-capture-toggle-accent" aria-hidden="true" />
          <label className="intro-capture-toggle-label">
            <input
              type="checkbox"
              checked={memoryAfterTaskEnabled}
              disabled={captureSettingsLoadState !== 'ready'}
              onChange={event => onMemoryChange(event.target.checked)}
            />
            <span className="intro-capture-toggle-body">
              <strong>Memory after tasks</strong>
              <span>I'll propose personal-profile updates after work we do together.</span>
            </span>
          </label>
          <details className="intro-toggle-details">
            <summary>What does this mean?</summary>
            <p>
              After I finish helping with a task, I'll review what happened and propose small
              updates to a personal profile: facts like what you do, who you write to most, the
              tone you prefer, and the kinds of questions you ask. You review every proposed
              memory before anything is saved, and you can edit or remove items any time in
              Settings. Change this later in <em>Personalization &gt; Personal Context</em>.
            </p>
          </details>
        </div>
        <div className="intro-capture-toggle intro-capture-toggle--skill">
          <span className="intro-capture-toggle-accent" aria-hidden="true" />
          <label className="intro-capture-toggle-label">
            <input
              type="checkbox"
              checked={skillAfterTaskEnabled}
              disabled={captureSettingsLoadState !== 'ready'}
              onChange={event => onSkillChange(event.target.checked)}
            />
            <span className="intro-capture-toggle-body">
              <strong>Reusable workflows</strong>
              <span>I'll propose named skills when a task goes well and seems repeatable.</span>
            </span>
          </label>
          <details className="intro-toggle-details">
            <summary>What does this mean?</summary>
            <p>
              When a task succeeds, I can pull the moves that worked into a small, named skill:
              something like "draft a weekly status email from my last three completed tasks" or
              "pull a meeting agenda from a Slack channel." Next time something similar comes up,
              I can run that skill instead of re-creating the steps from scratch — which gets you
              a useful result faster and more consistently, and means I can take more off your
              plate over time as the catalog grows. Think of them like recipes: once we've made
              a dish successfully, we don't have to figure out the steps from scratch the next
              time.
            </p>
            <p>
              You approve or edit each skill before it joins your catalog, and skills are easy
              to rewrite or delete later. Change this later in <em>Capabilities &gt; Automation &amp; Agents &gt; Skills</em>.
            </p>
          </details>
        </div>
      </fieldset>
    </div>
  )
}

interface IntroNoteStepProps {
  freeformNote: string
  onFreeformNoteChange: (value: string) => void
  styleGroups: InteractionStyleGroup[]
  styleSelections: InteractionStyleSelections
  onStyleSelectionsChange: (selections: InteractionStyleSelections) => void
}

function IntroNoteStep({
  freeformNote,
  onFreeformNoteChange,
  styleGroups,
  styleSelections,
  onStyleSelectionsChange,
}: IntroNoteStepProps) {
  const hasStyleGroups = styleGroups.length > 0

  return (
    <div className="intro-step-body">
      <h3>{hasStyleGroups ? 'How should I work with you?' : 'Anything else I should know?'}</h3>
      <p className="intro-step-lede">
        {hasStyleGroups
          ? 'Pick whatever is true of you. All optional.'
          : 'Optional. Tell me anything that helps me set things up your way.'}
      </p>

      <IntroInteractionStyle
        groups={styleGroups}
        selections={styleSelections}
        onSelectionsChange={onStyleSelectionsChange}
      />

      <label
        className="intro-freeform"
        style={{
          display: 'grid',
          gap: 8,
        }}
      >
        <span className="intro-freeform-label">{hasStyleGroups ? 'Anything else I should know?' : 'Note for me'}</span>
        <textarea
          value={freeformNote}
          onChange={event => onFreeformNoteChange(event.target.value)}
          placeholder="Tell me what you care about, ask a question, or leave this blank."
          rows={4}
          style={{
            border: '0.5px solid var(--separator-color)',
            borderRadius: 'var(--corner-radius-medium)',
            minHeight: 96,
            padding: '10px 12px',
            resize: 'vertical',
            width: '100%',
          }}
        />
      </label>
    </div>
  )
}
