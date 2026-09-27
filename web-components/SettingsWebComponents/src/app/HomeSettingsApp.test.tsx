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

  it('shows the Activity Capture and Meeting Detection launch hints ported from the deleted Background Behavior leaf', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const hints = Array.from(container.querySelectorAll('.home-settings-hint')).map((hint) => hint.textContent)
    expect(hints).toContain('Starts the capture scheduler after Basil reconnects to its backend on your next launch.')
    expect(hints).toContain("Turning this on also enables Meeting Detection; it won't start the monitor until the next launch.")
  })

  it('switches the Activity Capture hint to its disabled-feature wording when Activity Capture is off', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: { ...FIXTURE_FIELDS, activityCaptureEnabled: false } }) })
    expect(Array.from(container.querySelectorAll('.home-settings-hint')).map((hint) => hint.textContent))
      .toContain('Enable Automatic Capture in Activity Capture settings before choosing a startup schedule.')
  })

  it('posts an updateToggle intent and clears it on a successful intentResult', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const toggle = container.querySelector<HTMLInputElement>('#home-meeting-detection-enabled')!
    act(() => { toggle.click() })
    const call = postMessage.mock.calls.find(([message]) => message.type === 'updateToggle')!
    expect(call[0]).toEqual({ type: 'updateToggle', requestId: call[0].requestId, field: 'meetingDetectionEnabled', value: true })
    expect(container.querySelector('.home-settings-status')?.textContent).toBe('Saving setting...')
    act(() => { window.basilHomeSettings!.onEvent({ type: 'intentResult', requestId: call[0].requestId, status: 'success' }) })
    expect(container.querySelector('.home-settings-status')).toBeNull()
  })

  it('surfaces a load error with a retry action', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'loadError', message: 'Failed to load Home.' }) })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load Home.')
    act(() => { container.querySelector<HTMLButtonElement>('.home-settings-error button')!.click() })
    expect(postMessage.mock.calls.filter(([message]) => message.type === 'reactReady')).toHaveLength(2)
  })

  it('shows an inline error and restores the pending state to null after a failed intent', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    const toggle = container.querySelector<HTMLInputElement>('#home-enable-voice-listener')!
    act(() => { toggle.click() })
    const call = postMessage.mock.calls.find(([message]) => message.type === 'updateToggle')!
    act(() => { window.basilHomeSettings!.onEvent({ type: 'intentResult', requestId: call[0].requestId, status: 'error', message: 'Failed to update startup behavior.' }) })
    expect(container.querySelector('.home-settings-inline-error')?.textContent).toBe('Failed to update startup behavior.')
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
        fields: { ...FIXTURE_FIELDS, setupAssistantPending: false },
      })
    })
    expect(container.querySelector('.home-settings-resume-card')).toBeNull()
    act(() => { Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Open Setup Assistant')!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openSetupAssistant' }))
  })

  it('opens the Capabilities Guide from the setup card', () => {
    act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIXTURE_FIELDS }) })
    act(() => { Array.from(container.querySelectorAll('button')).find((button) => button.textContent === "Explore Basil's Capabilities")!.click() })
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'openPowerUserGuide' }))
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
