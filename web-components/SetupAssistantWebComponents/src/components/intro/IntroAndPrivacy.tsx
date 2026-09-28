import { useEffect, useRef, useState } from 'react'

import TokenizedSelect from '@shared/TokenizedSelect'

import { SmoothReveal } from './SmoothReveal'

import {
  fetchMemoryIntelligenceSettings,
  fetchModelAccessOptions,
  selectModelAccess,
  updateMemoryIntelligenceSettings,
} from '@/services/api'
import type {
  SetupAgentModelAccess,
  SetupAgentModelAccessMode,
  SetupAgentModelAccessOption,
} from '@/types'

interface Props {
  selectedModelAccess: SetupAgentModelAccess | null
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
  onContinue: (initialMessage: string) => void
}

type IntroStepName = 'model' | 'learning' | 'note'
type CaptureSettingsLoadState = 'loading' | 'ready' | 'unavailable'

const STEP_ORDER: readonly IntroStepName[] = ['model', 'learning', 'note'] as const
const STEP_TRANSITION_MS = 220

const modelChoices: Record<SetupAgentModelAccessMode, { title: string; detail: string }> = {
  local: {
    title: 'Local on this machine',
    detail: 'I\'ll reason through setup here. Nothing leaves unless you choose a connection.',
  },
  provider_key: {
    title: 'My own API key',
    detail: 'I\'ll use a model API key you provide directly to its provider.',
  },
  basil_cloud: {
    title: 'Basil Cloud',
    detail: 'Faster setup reasoning through your eligible Basil Cloud account.',
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

function getReduceMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function IntroAndPrivacy({
  selectedModelAccess,
  onSelectModelAccess,
  onContinue,
}: Props) {
  const [freeformNote, setFreeformNote] = useState('')
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

  useEffect(() => () => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current)
    }
  }, [])

  const advanceTo = (nextStep: IntroStepName) => {
    if (isTransitioning || nextStep === currentStep) return
    setErrorMessage(null)
    if (getReduceMotion()) {
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
    if (captureSettingsLoadState === 'unavailable') {
      onContinue(freeformNote.trim())
      return
    }

    setIsContinuing(true)
    setErrorMessage(null)
    try {
      await updateMemoryIntelligenceSettings({
        memory_after_task_enabled: memoryAfterTaskEnabled,
        skill_after_task_enabled: skillAfterTaskEnabled,
      })
      onContinue(freeformNote.trim())
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

      <div className="intro-step-footer">
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

        {stepIndex > 0 && (
          <button
            type="button"
            className="intro-step-back"
            onClick={goBack}
            disabled={isTransitioning || isContinuing}
          >
            ← Back
          </button>
        )}
      </div>
    </section>
  )
}

interface IntroModelStepProps {
  selectedModelAccess: SetupAgentModelAccess | null
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
  onConfirmingChange: (isConfirming: boolean) => void
}

type KeyValidationState = 'idle' | 'checking' | 'valid' | 'invalid'

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

  const providerKeyOption = options.find(option => option.mode === 'provider_key')
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
      })
      .catch(() => {
        if (isCurrent) setLoadState('unavailable')
      })
    return () => {
      isCurrent = false
    }
  }, [])

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
    if (!option.available || pendingMode) return

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
      <p className="intro-step-lede">There are a few ways I can do the thinking for this setup. They differ in speed, how sharp the reasoning is, and whether anything leaves this machine. Pick whichever fits how you want to work right now. I’ll confirm it before we continue.</p>

      <SmoothReveal open={loadState === 'loading'}>
        <p role="status">Checking available reasoning routes…</p>
      </SmoothReveal>
      <SmoothReveal open={loadState === 'unavailable'}>
        <p role="alert" style={{ color: 'var(--error-base)' }}>
          I couldn’t reach the setup service to check available reasoning routes.
        </p>
      </SmoothReveal>
      <SmoothReveal open={loadState === 'ready'}>
        <div className="choice-list" role="group" aria-label="Setup reasoning preference">
          {options.map(option => {
            const choice = modelChoices[option.mode]
            const selected = selectedModelAccess?.mode === option.mode
            const isExpandedProviderKey = option.mode === 'provider_key' && isProviderKeySelected
            const hasSavedProviderKey = option.mode === 'provider_key' && Boolean(savedProvider)
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
                  disabled={!option.available || pendingMode !== null}
                  onClick={() => void chooseRoute(option)}
                >
                  <div>
                    <strong>{choice.title}</strong>
                    <span>{pendingMode === option.mode && !isKeyFormOpen ? 'Confirming…' : choice.detail}</span>
                    {option.mode === 'provider_key' && (
                      <span className="choice-option-note">
                        Select this if you already have your own API key from a provider like Anthropic (Claude), OpenAI (ChatGPT), or Google (Gemini). I'll send setup requests directly to that provider using your key.
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
                    <p className="choice-option-key-help">
                      Don't have one yet?{' '}
                      <a href={providerKeyHelpUrls[provider]} target="_blank" rel="noreferrer">
                        Get a {providerLabels[provider]} API key
                      </a>
                      .
                    </p>
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

      <SmoothReveal open={Boolean(errorMessage)}>
        <p role="alert" style={{ color: 'var(--error-base)', margin: 0 }}>{errorMessage}</p>
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
            : <>Your saved choices are selected below. Nothing is saved without your approval. Change them later in <em>Personalization &gt; Personal Context</em> and <em>Capabilities &gt; Automation &amp; Agents &gt; Skills</em>.</>}
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
              Settings.
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
              to rewrite or delete later.
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
}

function IntroNoteStep({
  freeformNote,
  onFreeformNoteChange,
}: IntroNoteStepProps) {
  return (
    <div className="intro-step-body">
      <h3>Anything else I should know?</h3>
      <p className="intro-step-lede">
        Optional. Anything you tell me here helps me set things up the way you want. After
        this, I'll review what I can see locally and walk through the remaining setup items with you.
      </p>

      <label
        className="intro-freeform"
        style={{
          display: 'grid',
          gap: 8,
        }}
      >
        <span className="intro-freeform-label">Note for me</span>
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
