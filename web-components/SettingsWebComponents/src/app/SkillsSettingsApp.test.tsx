// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { SkillsSettingsApp } from './SkillsSettingsApp'
import type { SkillsInitEvent } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>

const BASE_INIT: SkillsInitEvent = {
  type: 'init',
  protocolVersion: 1,
  skillCandidates: [
    { id: 'c1', title: 'Draft weekly report', whenToUse: 'Weekly summaries', createdAt: '2026-08-01T00:00:00Z', observationCount: 3 },
    { id: 'c2', title: 'One-off cleanup', whenToUse: 'Rare cleanup', createdAt: '2026-08-02T00:00:00Z', observationCount: 1 },
  ],
  savedSkills: [
    { slug: 'weekly-report', title: 'Weekly report', whenToUse: 'Weekly summaries', version: 2, observationCount: 5, lastUsed: '2026-08-20T00:00:00Z', sizeBytes: 512, capBytes: 2048 },
  ],
  reconciliationActive: false,
  skillAfterTaskEnabled: true,
  skillDailyEnabled: false,
  skillDailyTimeLocal: '03:00',
  skillProcessingModel: null,
  skillReconciliationMinInstances: 2,
  availableSkillProcessingModels: [{ id: 'local-1', displayName: 'Local Model' }],
  pendingCandidateActionIDs: [],
  pendingSkillDeletionSlugs: [],
  isLoadingSkillsState: false,
  isRunningSkillsIntelligence: false,
  statusMessage: null,
}

beforeEach(() => {
  postMessage = vi.fn()
  window.webkit = { messageHandlers: { basilSkillsSettingsBridge: { postMessage } } }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => { root.render(<SkillsSettingsApp />) })
})

afterEach(() => {
  act(() => { root.unmount() })
  container.remove()
})

function sendInit(overrides: Partial<SkillsInitEvent> = {}) {
  act(() => { window.basilSkillsSettings!.onEvent({ ...BASE_INIT, ...overrides }) })
}

function lastMessageOfType(type: string) {
  return postMessage.mock.calls.map((call) => call[0]).reverse().find((message) => message.type === type)
}

describe('SkillsSettingsApp', () => {
  it('shows a loading state before init and notifies native it is ready', () => {
    expect(container.querySelector('.skills-settings-status')?.textContent).toContain('Loading Skill Intelligence')
    expect(postMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('renders the cadence summary and settings fields from init', () => {
    sendInit()
    expect(container.textContent).toContain('Runs after successful work')
    const afterTaskSwitch = container.querySelector<HTMLInputElement>('#skills-after-task-enabled')!
    expect(afterTaskSwitch.checked).toBe(true)
    const dailyTime = container.querySelector<HTMLInputElement>('#skills-daily-time')!
    expect(dailyTime.value).toBe('03:00')
    expect(dailyTime.disabled).toBe(true)
    const evaluatorSelect = container.querySelector<HTMLButtonElement>('[aria-label="Evaluator model"]')!
    expect(evaluatorSelect.textContent).toContain('Default reasoning model')
    act(() => { evaluatorSelect.click() })
    expect(document.querySelector('[role="listbox"]')?.textContent).toContain('Local Model')
  })

  it('sends requestUpdateSkillDailyEnabled and locks settings until native confirms it', () => {
    sendInit()
    const dailySwitch = container.querySelector<HTMLInputElement>('#skills-daily-enabled')!
    act(() => { dailySwitch.click() })
    expect(lastMessageOfType('requestUpdateSkillDailyEnabled')).toEqual(expect.objectContaining({ enabled: true }))
    const dailyTime = container.querySelector<HTMLInputElement>('#skills-daily-time')!
    expect(dailyTime.disabled).toBe(true)
  })

  it('sends requestUpdateSkillProcessingModel with null when reset to the default option', () => {
    sendInit({ skillProcessingModel: 'local-1' })
    const evaluatorSelect = container.querySelector<HTMLButtonElement>('[aria-label="Evaluator model"]')!
    act(() => { evaluatorSelect.click() })
    const defaultOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent === 'Default reasoning model')!
    act(() => { defaultOption.click() })
    expect(lastMessageOfType('requestUpdateSkillProcessingModel')).toEqual(expect.objectContaining({ modelId: null }))
  })

  it('increments and decrements the reconciliation threshold, clamping at the 1 and 20 boundaries', () => {
    sendInit({ skillReconciliationMinInstances: 1 })
    const minusButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === '-')!
    expect(minusButton.hasAttribute('disabled')).toBe(true)
    const plusButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === '+')!
    act(() => { plusButton.click() })
    expect(lastMessageOfType('requestUpdateSkillReconciliationMinInstances')).toEqual(expect.objectContaining({ minInstances: 2 }))
  })

  it('defaults to the Recurring tab and hides single-sighting candidates until switched', () => {
    sendInit()
    expect(container.textContent).toContain('Recurring (1)')
    expect(container.textContent).toContain('Single Sightings (1)')
    expect(container.textContent).toContain('Draft weekly report')
    expect(container.textContent).not.toContain('One-off cleanup')

    const singleSightingsTab = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Single Sightings (1)')!
    act(() => { singleSightingsTab.click() })
    expect(container.textContent).toContain('One-off cleanup')
    expect(container.textContent).not.toContain('Draft weekly report')
  })

  it('disables a declining candidate immediately and clears the local pending state on its result', () => {
    sendInit()
    const declineButtons = Array.from(container.querySelectorAll('button')).filter((b) => b.textContent === 'Decline')
    act(() => { declineButtons[0].click() })
    expect(lastMessageOfType('requestDeclineCandidate')).toEqual(expect.objectContaining({ id: 'c1' }))
    expect(declineButtons[0].disabled).toBe(true)
    expect(declineButtons[0].textContent).toBe('Declining…')
    const requestId = lastMessageOfType('requestDeclineCandidate')!.requestId as string
    act(() => {
      window.basilSkillsSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' })
    })
    expect(Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Decline')?.disabled).toBe(false)
  })

  it('sends requestDeleteSkill without a client-side confirmation (native shows the NSAlert)', () => {
    sendInit()
    const deleteButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Delete')!
    act(() => { deleteButton.click() })
    expect(lastMessageOfType('requestDeleteSkill')).toEqual(expect.objectContaining({ slug: 'weekly-report' }))
    expect(deleteButton.disabled).toBe(true)
    expect(deleteButton.textContent).toBe('Deleting…')
  })

  it('disables Run now while intelligence is running or reconciliation is active', () => {
    sendInit({ isRunningSkillsIntelligence: true })
    const runButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes('Running'))!
    expect(runButton.hasAttribute('disabled')).toBe(true)
  })

  it('disables Run now immediately to prevent duplicate requests', () => {
    sendInit()
    const runButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Run now')!
    act(() => { runButton.click() })
    expect(lastMessageOfType('requestRunIntelligenceNow')).toBeDefined()
    expect(runButton.disabled).toBe(true)
    expect(runButton.textContent).toBe('Running…')
  })

  it('shows the reconciliation lock overlay and hides the candidate/skill lists from assistive tech', () => {
    sendInit({ reconciliationActive: true })
    expect(container.querySelector('.skills-settings-lock-overlay')).not.toBeNull()
    expect(container.querySelector('.skills-settings-lists')?.getAttribute('aria-hidden')).toBe('true')
    const showWorkspaceButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Show Workspace')!
    act(() => { showWorkspaceButton.click() })
    expect(lastMessageOfType('focusReconciliationWorkspace')).toBeDefined()
  })

  it('opens the reconciliation workspace as a fire-and-forget message with no requestId', () => {
    sendInit()
    const openButton = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === 'Open Reconciliation Workspace')!
    act(() => { openButton.click() })
    const message = lastMessageOfType('openReconciliationWorkspace')
    expect(message).toEqual({ type: 'openReconciliationWorkspace' })
    expect(openButton.disabled).toBe(true)
    act(() => { openButton.click() })
    expect(postMessage.mock.calls.filter(([event]) => event.type === 'openReconciliationWorkspace')).toHaveLength(1)
  })

  it('renders statusMessage using the same "Error" substring heuristic native uses', () => {
    sendInit({ statusMessage: 'Error deleting skill: network unavailable' })
    const errorEl = container.querySelector('.skills-settings-inline-error')
    expect(errorEl?.textContent).toContain('Error deleting skill')
    expect(errorEl?.getAttribute('role')).toBe('alert')
  })

  it('surfaces an intentResult error as a dismissable inline message', () => {
    sendInit()
    const dailySwitch = container.querySelector<HTMLInputElement>('#skills-after-task-enabled')!
    act(() => { dailySwitch.click() })
    const requestId = lastMessageOfType('requestUpdateSkillAfterTaskEnabled')!.requestId as string
    act(() => {
      window.basilSkillsSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Failed to update skill settings.' })
    })
    expect(container.textContent).toContain('Failed to update skill settings.')
  })
})