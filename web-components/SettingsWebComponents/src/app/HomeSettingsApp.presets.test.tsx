// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { HomeSettingsApp } from './HomeSettingsApp'
import { planHomePreset } from './homePresets'
import type { HomeSettingsFields } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const FIELDS: HomeSettingsFields = {
  setupAssistantPending: false,
  setupAssistantCompleted: true,
  setupAssistantStateAvailable: true,
  permissionsGrantedCount: 3,
  permissionsTotalCount: 5,
  enableMonitoringAtStartup: true,
  enableVoiceListenerAtStartup: false,
  startActivityCaptureAtLaunch: false,
  startMeetingDetectionAtLaunch: false,
  backgroundBehaviorAvailable: true,
  activityCaptureEnabled: false,
  activityCaptureAvailable: true,
  meetingDetectionEnabled: false,
  meetingDetectionAvailable: true,
  proactiveSuggestionsEnabled: false,
  proactiveSuggestionsAvailable: true,
  localModels: [],
  apiModels: [],
  customModels: [],
  selectedModelId: '',
  useApiModels: false,
  reasoningModelsAvailable: true,
  localTranscriptionModels: [],
  apiTranscriptionModels: [],
  selectedTranscriptionModelId: '',
  transcriptionModelsAvailable: true,
}

function button(label: string): HTMLButtonElement {
  return Array.from(container.querySelectorAll('button')).find((candidate) => candidate.textContent === label)!
}

function toggles(): Array<{ field: string; value: boolean; requestId: string }> {
  return postMessage.mock.calls.map((call) => call[0]).filter((message) => message.type === 'updateToggle')
}

function confirmLastToggle(status: 'success' | 'error', fields: HomeSettingsFields) {
  const all = toggles()
  const last = all[all.length - 1]
  act(() => {
    window.basilHomeSettings!.onEvent({ type: 'snapshot', fields })
    window.basilHomeSettings!.onEvent({ type: 'intentResult', requestId: last.requestId, status, message: status === 'error' ? 'nope' : undefined })
  })
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilHomeSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<HomeSettingsApp onNavigate={() => {}} />) })
  act(() => { window.basilHomeSettings!.onEvent({ type: 'init', protocolVersion: 1, fields: FIELDS }) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

describe('planHomePreset', () => {
  it('lists only the differing, available settings, with features switched on before their launch options', () => {
    const plan = planHomePreset('everything', FIELDS)
    expect(plan.steps.map((step) => step.field)).toEqual([
      'enableVoiceListenerAtStartup',
      'activityCaptureEnabled',
      'startActivityCaptureAtLaunch',
      'meetingDetectionEnabled',
      'startMeetingDetectionAtLaunch',
      'proactiveSuggestionsEnabled',
    ])
    expect(plan.unavailable).toEqual([])
  })

  it('reports unavailable settings instead of silently skipping them', () => {
    const plan = planHomePreset('everything', { ...FIELDS, activityCaptureAvailable: false })
    expect(plan.steps.some((step) => step.field === 'activityCaptureEnabled')).toBe(false)
    expect(plan.unavailable).toEqual(['Activity Capture', 'Start Activity Capture on launch'])
  })

  it('conservative keeps hotkeys on and turns launch options off before their features', () => {
    const everythingOn = { ...FIELDS, enableVoiceListenerAtStartup: true, activityCaptureEnabled: true, startActivityCaptureAtLaunch: true, meetingDetectionEnabled: true, startMeetingDetectionAtLaunch: true, proactiveSuggestionsEnabled: true }
    const plan = planHomePreset('conservative', everythingOn)
    expect(plan.steps.map((step) => [step.field, step.value])).toEqual([
      ['enableVoiceListenerAtStartup', false],
      ['startActivityCaptureAtLaunch', false],
      ['activityCaptureEnabled', false],
      ['startMeetingDetectionAtLaunch', false],
      ['meetingDetectionEnabled', false],
      ['proactiveSuggestionsEnabled', false],
    ])
  })

  it('does nothing when the settings already match', () => {
    expect(planHomePreset('conservative', FIELDS).steps).toEqual([])
  })
})

describe('Quick Presets', () => {
  it('asks for confirmation before enabling everything and sends nothing on cancel', () => {
    act(() => { button('Enable everything').click() })
    expect(container.querySelector('[role="alertdialog"]')?.textContent).toContain('Activity Capture takes a screenshot of your screen on a schedule')
    expect(toggles()).toHaveLength(0)
    act(() => { button('Cancel').click() })
    expect(container.querySelector('[role="alertdialog"]')).toBeNull()
    expect(toggles()).toHaveLength(0)
  })

  it('applies settings one at a time, waiting for native to confirm each, then summarizes and mentions permissions', () => {
    act(() => { button('Enable everything').click() })
    act(() => { button('Yes, enable everything').click() })
    expect(toggles().map((toggle) => toggle.field)).toEqual(['enableVoiceListenerAtStartup'])

    let current = FIELDS
    const order = ['enableVoiceListenerAtStartup', 'activityCaptureEnabled', 'startActivityCaptureAtLaunch', 'meetingDetectionEnabled', 'startMeetingDetectionAtLaunch', 'proactiveSuggestionsEnabled']
    for (let index = 0; index < order.length; index += 1) {
      expect(toggles().map((toggle) => toggle.field)).toEqual(order.slice(0, index + 1))
      current = { ...current, [order[index]]: true }
      confirmLastToggle('success', current)
    }

    const status = container.querySelector('.home-settings-preset-status')!
    expect(status.textContent).toContain('Enable everything applied: 6 settings changed.')
    expect(status.textContent).toContain('3 of 5 granted')
    expect(status.textContent).toContain('never grants macOS permissions')
    expect(toggles()).toHaveLength(6)
  })

  it('stops at the first failure and says how many settings were left unchanged', () => {
    act(() => { button('Enable everything').click() })
    act(() => { button('Yes, enable everything').click() })
    confirmLastToggle('error', FIELDS)

    expect(toggles()).toHaveLength(1)
    const status = container.querySelector('.home-settings-preset-status.is-error')!
    expect(status.textContent).toContain('The preset stopped after a setting failed. 5 settings were not changed.')
    expect(container.querySelector<HTMLInputElement>('#home-enable-voice-listener')?.checked).toBe(false)
  })

  it('applies Conservative without a confirmation and reports when nothing needed to change', () => {
    act(() => { button('Conservative').click() })
    expect(toggles()).toHaveLength(0)
    expect(container.querySelector('.home-settings-preset-status')?.textContent).toBe('Conservative: nothing needed to change.')
  })
})
