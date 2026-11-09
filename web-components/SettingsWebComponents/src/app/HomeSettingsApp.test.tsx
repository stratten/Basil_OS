// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HomeSettingsApp, type HomeNavigationTarget } from './HomeSettingsApp'
import type { HomeSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let onNavigate: ReturnType<typeof vi.fn<(tab: HomeNavigationTarget) => void>>

const FIXTURE_FIELDS: HomeSettingsFields = {
  setupAssistantPending: true,
  setupAssistantCompleted: false,
  setupAssistantStateAvailable: true,
  permissionsGrantedCount: 3,
  permissionsTotalCount: 5,
  enableMonitoringAtStartup: true,
  enableVoiceListenerAtStartup: false,
  startActivityCaptureAtLaunch: false,
  startMeetingDetectionAtLaunch: false,
  backgroundBehaviorAvailable: true,
  activityCaptureEnabled: true,
  activityCaptureAvailable: true,
  meetingDetectionEnabled: false,
  meetingDetectionAvailable: true,
  proactiveSuggestionsEnabled: true,
  proactiveSuggestionsAvailable: true,
  localModels: [{ id: 'local-1', name: 'local-1', displayName: 'Local Model', provider: 'ollama', isApiModel: false }],
  apiModels: [],
  customModels: [],
  selectedModelId: 'local-1',
  useApiModels: false,
  reasoningModelsAvailable: true,
  localTranscriptionModels: [{ id: 'parakeet-1', displayName: 'Parakeet', isApiModel: false }],
  apiTranscriptionModels: [],
  selectedTranscriptionModelId: 'parakeet-1',
  transcriptionModelsAvailable: true,
}

beforeEach(() => {
  postMessage = vi.fn()
  onNavigate = vi.fn<(tab: HomeNavigationTarget) => void>()
  window.webkit = { messageHandlers: { basilHomeSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<HomeSettingsApp onNavigate={onNavigate} />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('HomeSettingsApp', () => {
  it('notifies ready on mount and shows a loading state until init arrives', () => {
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    expect(container.querySelector('.home-settings-status')?.textContent).toBe('Loading Home...')
  })

  it('renders the setup, compact controls, and model sections from init', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    expect(container.querySelector('#home-setup-heading')).not.toBeNull()
    expect(container.querySelector('.home-settings-readiness-row')?.textContent).toContain('3 of 5 granted')
    expect(container.querySelector('.home-settings-resume-card')).not.toBeNull()
    expect(container.querySelector<HTMLInputElement>('#home-enable-monitoring')?.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#home-activity-capture-enabled')?.checked).toBe(true)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')?.textContent).toContain('Local Model')
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Default transcription model"]')?.textContent).toContain('Parakeet')
    expect(container.querySelector('.home-settings-compact-grid')).not.toBeNull()
    expect(container.querySelector('.home-settings-model-controls')).not.toBeNull()
    expect(container.querySelector('.home-settings-account-row')).toBeNull()
  })

  const tooltips = () => Array.from(container.querySelectorAll('.hint-tooltip-trigger')).map((trigger) => trigger.getAttribute('data-tooltip'))

  it('shows the Activity Capture and Meeting/Call Detection launch explanations in tooltips', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    expect(tooltips()).toContain('Activity Capture starts by itself each time Basil opens, beginning with your next launch.')
    expect(tooltips()).toContain('Turning this on also turns on Meeting/Call Detection. It starts watching for calls the next time Basil opens.')
  })

  it('switches the Activity Capture tooltip to its disabled-feature wording when Activity Capture is off', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: { ...FIXTURE_FIELDS, activityCaptureEnabled: false } }) })
    expect(tooltips()).toContain('Turn on Automatic Capture in Activity Capture settings first. Then you can have it start when Basil opens.')
  })

  it('explains each switch that starts something in the background through a circled question mark, not a line of text', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    expect(tooltips()).toContain('Voice Listener listens through your microphone so you can start things by voice. It needs microphone access.')
    expect(tooltips()).toContain('Takes a screenshot of your screen on a schedule and has a model read it. Where that reading happens depends on the model you pick in Activity Capture settings.')
    expect(tooltips()).toContain('Notices when a meeting or call starts on this Mac.')
    expect(tooltips()).toContain('Lets me offer help without being asked, when your settings allow it.')
    const trigger = container.querySelector<HTMLButtonElement>('[aria-label="About Voice Listener"]')!
    expect(trigger.textContent).toBe('?')
    expect(trigger.getAttribute('data-tooltip')).toContain('Voice Listener listens through your microphone')
    expect(container.querySelector('.hint-tooltip-bubble')).toBeNull()
    expect(container.querySelector('#home-enable-monitoring')?.closest('label')?.textContent).toContain('Enable hotkeys at startup')
    const sectionHints = Array.from(container.querySelectorAll('.home-settings-hint')).map((hint) => hint.textContent ?? '')
    expect(sectionHints.some((text) => text.includes('listens through your microphone'))).toBe(false)
  })

  it('puts Quick Presets first and Report a problem second in the right rail, after all the other content', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const layout = container.querySelector('.home-settings-layout')!
    const [main, rail] = Array.from(layout.children)
    expect(main.classList.contains('home-settings-main')).toBe(true)
    expect(rail.classList.contains('home-settings-rail')).toBe(true)
    expect(Array.from(rail.querySelectorAll('h2')).map((heading) => heading.textContent)).toEqual(['Quick Presets', 'Support'])
    expect(main.textContent).not.toContain('Report a problem')
    expect(rail.querySelector('#home-support-heading')?.closest('section')?.textContent).toContain('Report a problem')
  })

  it('tucks each preset explanation into a closed expandable block under its button', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const blocks = Array.from(container.querySelectorAll<HTMLDetailsElement>('.home-settings-preset-details'))
    expect(blocks.map((block) => block.open)).toEqual([false, false])
    expect(blocks[0].textContent).toContain('Turns on Voice Listener, Activity Capture, Meeting/Call Detection, Proactive Suggestions, and their startup options.')
    expect(blocks[1].textContent).toContain('Keeps only hotkeys on and turns the rest off.')
    expect(blocks[0].previousElementSibling?.textContent?.trim()).toBe('Enable everything')
    expect(blocks[1].previousElementSibling?.textContent?.trim()).toBe('Conservative')
  })

  it('posts an updateToggle intent, applies it immediately, and keeps other controls interactive until native confirms', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const toggle = container.querySelector<HTMLInputElement>('#home-meeting-detection-enabled')!
    act(() => { toggle.click() })
    const call = postMessage.mock.calls.find(([message]) => message.type === 'updateToggle')!
    expect(call[0]).toEqual({ type: 'updateToggle', requestId: call[0].requestId, field: 'meetingDetectionEnabled', value: true })
    expect(toggle.checked).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#home-enable-monitoring')!.disabled).toBe(false)
    expect(container.querySelector('.settings-visually-hidden')?.textContent).toBe('Saving setting...')
    act(() => { window.basilHomeSettings!.onEvent({ type: 'intentResult', requestId: call[0].requestId, status: 'success' }) })
    expect(container.querySelector('.settings-visually-hidden')?.textContent).toBe('')
    expect(toggle.checked).toBe(true)
  })

  it('surfaces a load error with a retry action', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'loadError', message: 'Failed to load Home.' }) })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load Home.')
    act(() => { container.querySelector<HTMLButtonElement>('.home-settings-error button')!.click() })
    expect(postMessage.mock.calls.filter(([message]) => message.type === 'reactReady')).toHaveLength(2)
  })

  it('shows an inline error and reverts the toggle after a failed intent', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const toggle = container.querySelector<HTMLInputElement>('#home-enable-voice-listener')!
    act(() => { toggle.click() })
    const call = postMessage.mock.calls.find(([message]) => message.type === 'updateToggle')!
    act(() => { window.basilHomeSettings!.onEvent({ type: 'intentResult', requestId: call[0].requestId, status: 'error', message: 'Failed to update startup behavior.' }) })
    expect(container.querySelector('.home-settings-inline-error')?.textContent).toBe('Failed to update startup behavior.')
    expect(toggle.checked).toBe(false)
  })

  it('calls onNavigate for the permissions and Models links', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Review')!.click() })
    expect(onNavigate).toHaveBeenCalledWith('permissions')
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Manage models')!.click() })
    expect(onNavigate).toHaveBeenCalledWith('models')
  })

  it('opens the Setup Assistant when the resume card action is clicked', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Resume Setup')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openSetupAssistant' }))
  })

  it('keeps the Setup Assistant launcher available after setup is complete', () => {
    act(() => {
      window.basilHomeSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        fields: { ...FIXTURE_FIELDS, setupAssistantPending: false, setupAssistantCompleted: true },
      })
    })
    expect(container.querySelector('.home-settings-resume-card')).toBeNull()
    expect(container.querySelector('.home-settings-setup-notice')).toBeNull()
    expect(container.querySelector('.home-settings-setup-badge.is-complete')?.textContent).toBe('Setup complete')
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Open Setup Assistant')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openSetupAssistant' }))
  })

  it('draws attention to setup that was never finished', () => {
    act(() => {
      window.basilHomeSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        fields: { ...FIXTURE_FIELDS, setupAssistantPending: false, setupAssistantCompleted: false },
      })
    })
    expect(container.querySelector('.home-settings-setup-notice')?.textContent).toContain("Basil isn't fully set up yet.")
    expect(container.querySelector('.home-settings-setup-badge.is-incomplete')?.textContent).toBe('Setup incomplete')
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Start Setup')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openSetupAssistant' }))
  })

  it('marks skipped setup incomplete alongside the resume card without duplicating the notice', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    expect(container.querySelector('.home-settings-resume-card')).not.toBeNull()
    expect(container.querySelector('.home-settings-setup-notice')).toBeNull()
    expect(container.querySelector('.home-settings-setup-badge.is-incomplete')?.textContent).toBe('Setup incomplete')
  })

  it('shows no setup badge or notice when setup status is unavailable', () => {
    act(() => {
      window.basilHomeSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        fields: { ...FIXTURE_FIELDS, setupAssistantPending: false, setupAssistantCompleted: false, setupAssistantStateAvailable: false },
      })
    })
    expect(container.querySelector('.home-settings-setup-badge')).toBeNull()
    expect(container.querySelector('.home-settings-setup-notice')).toBeNull()
    expect(Array.from(container.querySelectorAll('button')).some((b) => b.textContent === 'Open Setup Assistant')).toBe(true)
  })

  it('opens the Capabilities Guide from the setup card', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    act(() => { Array.from(container.querySelectorAll('button')).find((button) => button.textContent === "Explore Basil's Capabilities")!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openPowerUserGuide' }))
  })

  it('offers Report a problem from the Support card and says nothing is sent until the issue is submitted', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    act(() => { Array.from(container.querySelectorAll('button')).find((button) => button.textContent === 'Report a problem')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'reportProblem', requestId: expect.any(String) }))
    expect(container.textContent).toContain('Nothing is sent until you submit the issue.')
  })

  it('disables unavailable controls and explains the degraded snapshot', () => {
    act(() => {
      window.basilHomeSettings!.onEvent({
        type: 'init',
        protocolVersion: 1,
        fields: {
          ...FIXTURE_FIELDS,
          backgroundBehaviorAvailable: false,
          activityCaptureAvailable: false,
          reasoningModelsAvailable: false,
        },
      })
    })
    expect(container.querySelector<HTMLInputElement>('#home-enable-monitoring')?.disabled).toBe(true)
    expect(container.querySelector<HTMLInputElement>('#home-activity-capture-enabled')?.disabled).toBe(true)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Default reasoning model"]')?.disabled).toBe(true)
    expect(container.textContent).toContain('Hotkey and Voice Listener preferences are temporarily unavailable.')
  })
})
