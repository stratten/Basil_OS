// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearanceSettingsApp } from './AppearanceSettingsApp'
import { APPEARANCE_FIXTURE_SETTINGS } from '../fixtures/appearanceFixture'
import type { AppearanceNativeEvent } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let dateTimePostMessage: ReturnType<typeof vi.fn>

function emit(event: AppearanceNativeEvent) {
  act(() => {
    window.basilAppearanceSettings!.onEvent(event)
  })
}

function initEvent(overrides: Partial<typeof APPEARANCE_FIXTURE_SETTINGS> = {}) {
  return {
    type: 'init' as const,
    protocolVersion: 1 as const,
    revision: 1,
    settings: { ...APPEARANCE_FIXTURE_SETTINGS, ...overrides },
    availableFonts: ['Helvetica-Light', 'Arial', 'Avenir-Light', 'SF Pro Text', 'Menlo'],
    theme: {
      backgroundPrimary: '#FFFFFF', backgroundSecondary: '#FFFFFF', backgroundTertiary: '#FFFFFF',
      primary: '#00308C', secondary: '#335599', textPrimary: '#000000', textSecondary: '#666666',
      textTertiary: '#999999', separatorColor: '#CCCCCC', fieldBorder: '#CCCCCC', recordingBase: '#8B0000',
      recordingAccent: '#FF6347', processingBase: '#7C3AED', processingAccent: '#DDD6FE', warningBase: '#FFA500',
    },
    fonts: { fontFamily: 'Helvetica-Light', fontFamilyMedium: 'Helvetica', fontFamilyBold: 'Helvetica-Bold' },
  }
}

function pickPrimaryColor() {
  emit({ type: 'colorPicked', fieldId: 'primary', red: 1, green: 0, blue: 0 })
}

function primaryColorTrigger() {
  return container.querySelector<HTMLButtonElement>('#appearance-primary-color')!
}

beforeEach(() => {
  postMessage = vi.fn()
  dateTimePostMessage = vi.fn()
  window.webkit = {
    messageHandlers: {
      basilAppearanceSettingsBridge: { postMessage },
      basilDateTimeSettingsBridge: { postMessage: dateTimePostMessage },
    },
  }
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  act(() => {
    root.render(<AppearanceSettingsApp />)
  })
})

afterEach(() => {
  act(() => {
    root.unmount()
  })
  container.remove()
})

describe('AppearanceSettingsApp', () => {
  it('does not expose fixture values as editable settings before native initialization', () => {
    expect(container.querySelector('[role="status"]')?.textContent).toBe('Loading appearance settings...')
    expect(container.querySelector('#appearance-primary-color')).toBeNull()
  })

  it('adopts a clean init snapshot and keeps Save/Cancel disabled', () => {
    emit(initEvent())
    const saveButton = container.querySelector<HTMLButtonElement>('button.primary-button')!
    expect(saveButton.disabled).toBe(true)
  })

  it('requests the native picker from the compact color trigger', () => {
    emit(initEvent())
    act(() => {
      primaryColorTrigger().click()
    })
    expect(postMessage).toHaveBeenCalledWith({
      type: 'openColorPicker',
      fieldId: 'primary',
      red: 0,
      green: 0.188,
      blue: 0.529,
    })
  })

  it('applies all four preset colors at once and keeps them independently editable afterward', async () => {
    emit(initEvent())
    const precursorSwatch = container.querySelector<HTMLButtonElement>('[aria-label="Precursor"]')!
    act(() => {
      precursorSwatch.click()
    })
    await new Promise((resolve) => window.requestAnimationFrame(resolve))
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'previewDraft',
        draft: expect.objectContaining({
          backgroundColorRed: 0.369,
          backgroundColorGreen: 0.192,
          backgroundColorBlue: 0.086,
          primaryColorRed: 1,
          primaryColorGreen: 0.675,
          primaryColorBlue: 0.435,
          secondaryColorRed: 0.176,
          secondaryColorGreen: 0.698,
          secondaryColorBlue: 0.737,
          textColorRed: 1,
          textColorGreen: 0.973,
          textColorBlue: 0.906,
        }),
      }),
    )

    pickPrimaryColor()
    await new Promise((resolve) => window.requestAnimationFrame(resolve))
    expect(postMessage).toHaveBeenLastCalledWith(
      expect.objectContaining({
        type: 'previewDraft',
        draft: expect.objectContaining({ primaryColorRed: 1, primaryColorGreen: 0, primaryColorBlue: 0 }),
      }),
    )
  })

  it('enables Save/Cancel and sends a coalesced previewDraft on a color edit', async () => {
    emit(initEvent())
    pickPrimaryColor()
    await new Promise((resolve) => window.requestAnimationFrame(resolve))

    const saveButton = container.querySelector<HTMLButtonElement>('button.primary-button')!
    expect(saveButton.disabled).toBe(false)
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'previewDraft' }))
  })

  it('disables Save/Cancel while a save is pending and clears dirty state on save success', () => {
    emit(initEvent())
    pickPrimaryColor()

    const saveButton = container.querySelector<HTMLButtonElement>('button.primary-button')!
    act(() => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(saveButton.disabled).toBe(true)

    const saveCall = postMessage.mock.calls.find((call) => call[0].type === 'saveDraft')!
    const requestId = saveCall[0].requestId as string
    const savedSettings = saveCall[0].draft

    emit({ type: 'snapshot', protocolVersion: 1, revision: 2, settings: savedSettings, availableFonts: ['Helvetica-Light'] })
    emit({ type: 'intentResult', requestId, status: 'success' })

    expect(saveButton.disabled).toBe(true)
  })

  it('shows an inline error and re-enables Save on save failure, preserving the dirty draft', () => {
    emit(initEvent())
    pickPrimaryColor()
    const saveButton = container.querySelector<HTMLButtonElement>('button.primary-button')!
    act(() => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const requestId = postMessage.mock.calls.find((call) => call[0].type === 'saveDraft')![0].requestId as string

    emit({ type: 'intentResult', requestId, status: 'error', message: 'Backend unavailable.' })

    expect(container.querySelector('.appearance-save-bar-error')?.textContent).toBe('Backend unavailable.')
    expect(saveButton.disabled).toBe(false)
    expect(primaryColorTrigger().style.backgroundColor).toBe('rgb(255, 0, 0)')
  })

  it('restores the persisted draft immediately on Cancel and sends cancelDraft', () => {
    emit(initEvent())
    pickPrimaryColor()
    const cancelButton = container.querySelector<HTMLButtonElement>('button.secondary-button')!
    act(() => {
      cancelButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(primaryColorTrigger().style.backgroundColor).toBe('rgb(0, 48, 135)')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'cancelDraft' }))
  })

  it('resets the draft to defaults locally and sends resetDraft without persistence', () => {
    emit(initEvent())
    const resetButton = container.querySelector<HTMLButtonElement>('.appearance-reset-button')!
    act(() => {
      resetButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(primaryColorTrigger().style.backgroundColor).toBe('rgb(54, 120, 227)')
    expect(postMessage).toHaveBeenCalledWith(expect.objectContaining({ type: 'resetDraft' }))
    expect(postMessage.mock.calls.some((call) => call[0].type === 'saveDraft')).toBe(false)
  })

  it('shows a non-destructive reload banner instead of overwriting a dirty draft on an external snapshot, and reload adopts it', () => {
    emit(initEvent())
    pickPrimaryColor()

    const externalSettings = { ...APPEARANCE_FIXTURE_SETTINGS, backgroundColorRed: 0.9 }
    emit({ type: 'snapshot', protocolVersion: 1, revision: 5, settings: externalSettings, availableFonts: ['Helvetica-Light'] })

    expect(primaryColorTrigger().style.backgroundColor).toBe('rgb(255, 0, 0)')
    const banner = container.querySelector('.appearance-external-change-banner')
    expect(banner).not.toBeNull()

    const reloadButton = banner!.querySelector<HTMLButtonElement>('button')!
    act(() => {
      reloadButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.querySelector('.appearance-external-change-banner')).toBeNull()
    expect(primaryColorTrigger().style.backgroundColor).toBe('rgb(0, 48, 135)')
  })

  it('preserves all six processing-color fields byte-for-byte through a displayed-field save', () => {
    emit(initEvent())
    pickPrimaryColor()
    const saveButton = container.querySelector<HTMLButtonElement>('button.primary-button')!
    act(() => {
      saveButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const savedDraft = postMessage.mock.calls.find((call) => call[0].type === 'saveDraft')![0].draft
    expect(savedDraft.processingColorRed).toBe(APPEARANCE_FIXTURE_SETTINGS.processingColorRed)
    expect(savedDraft.processingColorGreen).toBe(APPEARANCE_FIXTURE_SETTINGS.processingColorGreen)
    expect(savedDraft.processingColorBlue).toBe(APPEARANCE_FIXTURE_SETTINGS.processingColorBlue)
    expect(savedDraft.processingAccentColorRed).toBe(APPEARANCE_FIXTURE_SETTINGS.processingAccentColorRed)
    expect(savedDraft.processingAccentColorGreen).toBe(APPEARANCE_FIXTURE_SETTINGS.processingAccentColorGreen)
    expect(savedDraft.processingAccentColorBlue).toBe(APPEARANCE_FIXTURE_SETTINGS.processingAccentColorBlue)
  })

  it('notifies the Date & Time bridge ready and renders the persisted style once init arrives', () => {
    expect(dateTimePostMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
    act(() => {
      window.basilDateTimeSettings!.onEvent({ type: 'init', protocolVersion: 1, dateDisplayStyle: 'relative' })
    })
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')?.textContent).toContain('Relative')
  })

  it('sends updateDateDisplayStyle on change and adopts the resulting snapshot', () => {
    act(() => {
      window.basilDateTimeSettings!.onEvent({ type: 'init', protocolVersion: 1, dateDisplayStyle: 'relative' })
    })
    const select = container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')!
    act(() => { select.click() })
    const absoluteOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent?.startsWith('Absolute'))!
    act(() => { absoluteOption.click() })
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')!.disabled).toBe(true)
    expect(dateTimePostMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'updateDateDisplayStyle', dateDisplayStyle: 'absolute' }),
    )
    const requestId = dateTimePostMessage.mock.calls.find((call) => call[0].type === 'updateDateDisplayStyle')![0].requestId as string
    act(() => {
      window.basilDateTimeSettings!.onEvent({ type: 'intentResult', requestId, status: 'success' })
      window.basilDateTimeSettings!.onEvent({ type: 'snapshot', dateDisplayStyle: 'absolute' })
    })
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')!.disabled).toBe(false)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')?.textContent).toContain('Absolute')
  })

  it('restores the last confirmed date display style when its immediate save fails', () => {
    act(() => {
      window.basilDateTimeSettings!.onEvent({ type: 'init', protocolVersion: 1, dateDisplayStyle: 'relative' })
    })
    const select = container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')!
    act(() => { select.click() })
    const absoluteOption = Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find((option) => option.textContent?.startsWith('Absolute'))!
    act(() => { absoluteOption.click() })
    const requestId = dateTimePostMessage.mock.calls.find((call) => call[0].type === 'updateDateDisplayStyle')![0].requestId as string
    act(() => {
      window.basilDateTimeSettings!.onEvent({ type: 'intentResult', requestId, status: 'error', message: 'Backend unavailable.' })
    })
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')!.disabled).toBe(false)
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Date Display"]')?.textContent).toContain('Relative')
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Backend unavailable.')
  })
})
