import { useEffect, useRef, useState } from 'react'

import {
  fetchMemoryIntelligenceSettings,
  updateMemoryIntelligenceSettings,
} from '@/services/api'
import type { SetupAgentModelAccess, SetupAgentModelAccessMode } from '@/types'

interface Props {
  selectedModelAccess: SetupAgentModelAccess
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
  onContinue: (initialMessage: string) => void
}

type IntroStepName = 'model' | 'learning' | 'note'
type CaptureSettingsLoadState = 'loading' | 'ready' | 'unavailable'

const STEP_ORDER: readonly IntroStepName[] = ['model', 'learning', 'note'] as const
const STEP_TRANSITION_MS = 220

const modelChoices: Array<{
  mode: SetupAgentModelAccessMode
  title: string
  detail: string
}> = [
  {
    mode: 'local',
    title: 'Local on this machine',
    detail: 'I\'ll reason through setup here. Nothing leaves unless you choose a connection.',
  },
  {
    mode: 'default_proxy',
    title: 'Recommended cloud model',
    detail: 'Faster, smarter setup reasoning through the recommended Basil Cloud model.',
  },
  {
    mode: 'custom',
    title: 'A model I\'ve already set up',
    detail: 'I\'ll use the setup-compatible model you have already configured in Settings.',
  },
]

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
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const [currentStep, setCurrentStep] = useState<IntroStepName>('model')
  const [pendingStep, setPendingStep] = useState<IntroStepName | null>(null)
  const transitionTimerRef = useRef<number | null>(null)

  const stepIndex = STEP_ORDER.indexOf(currentStep)
  const isFinalStep = currentStep === 'note'
  const isTransitioning = pendingStep !== null

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
    if (isContinuing || captureSettingsLoadState === 'loading') return
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
          disabled={isTransitioning || isContinuing || (currentStep === 'learning' && captureSettingsLoadState === 'loading')}
        >
          {currentStep === 'learning' && captureSettingsLoadState === 'loading'
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
  selectedModelAccess: SetupAgentModelAccess
  onSelectModelAccess: (modelAccess: SetupAgentModelAccess) => void
}

function IntroModelStep({
  selectedModelAccess,
  onSelectModelAccess,
}: IntroModelStepProps) {
  return (
    <div className="intro-step-body">
      <h3>Reasoning during setup</h3>
      <p className="intro-step-lede">
        There are a few ways I can do the thinking for this setup. They differ in speed,
        how sharp the reasoning is, and whether anything leaves this machine. Pick whichever
        fits how you want to work right now — you can change it later.
      </p>

      <div className="choice-list" role="group" aria-label="Setup reasoning preference">
        {modelChoices.map(choice => (
          <button
            key={choice.mode}
            type="button"
            className={[
              'choice-option',
              `choice-option--${choice.mode}`,
              selectedModelAccess.mode === choice.mode ? 'selected' : '',
            ].join(' ')}
            aria-pressed={selectedModelAccess.mode === choice.mode}
            onClick={() => onSelectModelAccess({
              mode: choice.mode,
              custom_model_id: null,
              local_model_id: null,
            })}
          >
            <div>
              <strong>{choice.title}</strong>
              <span>{choice.detail}</span>
            </div>
          </button>
        ))}
      </div>

      <details className="intro-help">
        <summary>
          <span>What's the difference?</span>
          <span className="intro-help-chevron" aria-hidden="true">›</span>
        </summary>
        <div className="intro-help-body">
          <dl>
            <div>
              <dt>Local on this machine</dt>
              <dd>
                I reason here using a local model on your disk. Slower than the cloud option and I
                use some memory while I'm thinking, but this setup conversation stays on this
                machine.
              </dd>
            </div>
            <div>
              <dt>Recommended cloud model</dt>
              <dd>
                I reason through a stronger model hosted by Basil Cloud. Faster and smarter, but
                the contents of this conversation are routed through Basil Cloud while I am
                working.
              </dd>
            </div>
            <div>
              <dt>A model I've already set up</dt>
              <dd>
                I'll use the specific reasoning model you have already configured in Settings. Best
                when you already know which one you want here.
              </dd>
            </div>
          </dl>
          <p className="intro-help-footnote">
            This only governs how I think during setup. It does not lock in how I reason later —
            you can change my main models any time in Settings.
          </p>
        </div>
      </details>
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
