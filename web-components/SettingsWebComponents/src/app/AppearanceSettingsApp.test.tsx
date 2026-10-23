// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { AppearanceSettingsApp } from './AppearanceSettingsApp'
import { APPEARANCE_FIXTURE_SETTINGS } from '../fixtures/appearanceFixture'
import type { AppearanceNativeEvent, AppearanceThemesNativeEvent, CustomAppearanceTheme } from '../types'

let container: HTMLElement
let root: Root
let postMessage: ReturnType<typeof vi.fn>
let dateTimePostMessage: ReturnType<typeof vi.fn>
let themesPostMessage: ReturnType<typeof vi.fn>

const HARBOR_THEME: CustomAppearanceTheme = {
  id: 'custom-0123456789abcdef0123456789abcdef',
  name: 'Harbor',
  backgroundColorRed: 0.1,
  backgroundColorGreen: 0.2,
  backgroundColorBlue: 0.3,
  primaryColorRed: 0.4,
  primaryColorGreen: 0.5,
  primaryColorBlue: 0.6,
  secondaryColorRed: 0.7,
  secondaryColorGreen: 0.8,
  secondaryColorBlue: 0.9,
  textColorRed: 1,
  textColorGreen: 0.95,
  textColorBlue: 0.9,
  surfaceFinish: 'metal',
}

function emitThemes(event: AppearanceThemesNativeEvent) {
  act(() => {
    window.basilAppearanceThemes!.onEvent(event)
  })
}

function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')?.set
  act(() => {
    setter?.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function buttonWithText(text: string) {
  return Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find((button) => button.textContent === text)
}

function openSaveThemeForm(name: string) {
  act(() => {
    buttonWithText('Save as Theme')!.click()
  })
  typeInto(container.querySelector<HTMLInputElement>('#appearance-save-theme-name')!, name)
}

function submitSaveThemeForm() {
  act(() => {
    container
      .querySelector<HTMLFormElement>('form.appearance-save-theme')!
      .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
}

function previewDraftCallCount() {
  return postMessage.mock.calls.filter((call) => call[0].type === 'previewDraft').length
}

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
  themesPostMessage = vi.fn()
  window.webkit = {
    messageHandlers: {
      basilAppearanceSettingsBridge: { postMessage },
      basilDateTimeSettingsBridge: { postMessage: dateTimePostMessage },
      basilAppearanceThemesBridge: { postMessage: themesPostMessage },
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

  it('offers a background-only metallic finish and previews it like the other finishes', async () => {
    emit(initEvent())
    await new Promise((resolve) => window.requestAnimationFrame(resolve))
    const options = Array.from(container.querySelectorAll<HTMLButtonElement>('.appearance-finish-option')).map((button) => button.textContent)
    expect(options).toEqual(['Flat', 'Metallic', 'Metallic (background only)'])

    act(() => { buttonWithText('Metallic (background only)')!.click() })
    await new Promise((resolve) => window.requestAnimationFrame(resolve))

    expect(container.querySelector<HTMLButtonElement>('.appearance-finish-option[aria-pressed="true"]')?.textContent).toBe('Metallic (background only)')
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'previewDraft', draft: expect.objectContaining({ surfaceFinish: 'metal_backdrop' }) }),
    )
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
    const cancelButton = container.querySelector<HTMLButtonElement>('.appearance-save-bar button.secondary-button')!
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

describe('AppearanceSettingsApp custom themes', () => {
  it('notifies the themes bridge ready on mount, before Appearance itself initializes', () => {
    expect(themesPostMessage).toHaveBeenCalledWith({ type: 'reactReady', protocolVersion: 1 })
  })

  it('renders saved themes after the built-in presets with a delete control only on saved themes', () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [HARBOR_THEME] })
    const swatches = container.querySelectorAll('.appearance-preset-swatch')
    expect(swatches[swatches.length - 1].getAttribute('aria-label')).toBe('Harbor')
    expect(container.querySelectorAll('.appearance-preset-swatch-delete').length).toBe(1)
    expect(container.querySelector('[aria-label="Delete theme Precursor"]')).toBeNull()
  })

  it('applies a saved theme’s four colors and finish while preserving every other field', async () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [HARBOR_THEME] })
    act(() => {
      container.querySelector<HTMLButtonElement>('.appearance-preset-swatch[aria-label="Harbor"]')!.click()
    })
    await new Promise((resolve) => window.requestAnimationFrame(resolve))
    expect(postMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'previewDraft',
        draft: expect.objectContaining({
          backgroundColorRed: 0.1,
          backgroundColorGreen: 0.2,
          backgroundColorBlue: 0.3,
          primaryColorRed: 0.4,
          primaryColorGreen: 0.5,
          primaryColorBlue: 0.6,
          secondaryColorRed: 0.7,
          secondaryColorGreen: 0.8,
          secondaryColorBlue: 0.9,
          textColorRed: 1,
          textColorGreen: 0.95,
          textColorBlue: 0.9,
          surfaceFinish: 'metal',
          processingColorRed: 0.486,
          preferredFont: 'Helvetica-Light',
        }),
      }),
    )
    expect(container.querySelector<HTMLButtonElement>('.appearance-finish-option[aria-pressed="true"]')?.textContent).toBe('Metallic')
  })

  it('saves the on-screen draft, including unsaved edits, as a named theme without saving the active appearance', () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [] })
    pickPrimaryColor()
    openSaveThemeForm('  Harbor  ')
    submitSaveThemeForm()

    const saveCall = themesPostMessage.mock.calls.find((call) => call[0].type === 'saveTheme')!
    expect(saveCall[0].theme).toEqual({
      name: 'Harbor',
      backgroundColorRed: 1,
      backgroundColorGreen: 1,
      backgroundColorBlue: 1,
      primaryColorRed: 1,
      primaryColorGreen: 0,
      primaryColorBlue: 0,
      secondaryColorRed: 0.2,
      secondaryColorGreen: 0.333,
      secondaryColorBlue: 0.608,
      textColorRed: 0,
      textColorGreen: 0,
      textColorBlue: 0,
      surfaceFinish: 'flat',
    })
    expect(postMessage.mock.calls.some((call) => call[0].type === 'saveDraft')).toBe(false)
    expect(buttonWithText('Saving…')?.disabled).toBe(true)

    const savedTheme: CustomAppearanceTheme = { ...saveCall[0].theme, id: HARBOR_THEME.id }
    emitThemes({ type: 'snapshot', themes: [savedTheme] })
    emitThemes({ type: 'intentResult', requestId: saveCall[0].requestId, status: 'success' })

    expect(container.querySelector('#appearance-save-theme-name')).toBeNull()
    expect(container.querySelector('.appearance-preset-swatch[aria-label="Harbor"]')).not.toBeNull()
    expect(buttonWithText('Save as Theme')?.disabled).toBe(false)
    expect(container.querySelector<HTMLButtonElement>('button.primary-button')!.disabled).toBe(false)
  })

  it('rejects blank and duplicate names locally without contacting native', () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [HARBOR_THEME] })
    openSaveThemeForm('precursor')
    submitSaveThemeForm()
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('A theme with that name already exists.')

    typeInto(container.querySelector<HTMLInputElement>('#appearance-save-theme-name')!, ' harbor ')
    submitSaveThemeForm()
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('A theme with that name already exists.')

    typeInto(container.querySelector<HTMLInputElement>('#appearance-save-theme-name')!, '   ')
    submitSaveThemeForm()
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Enter a theme name.')
    expect(themesPostMessage.mock.calls.some((call) => call[0].type === 'saveTheme')).toBe(false)
  })

  it('keeps the form open with the typed name and shows the native error when saving fails', () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [] })
    openSaveThemeForm('Harbor')
    submitSaveThemeForm()
    const requestId = themesPostMessage.mock.calls.find((call) => call[0].type === 'saveTheme')![0].requestId as string
    emitThemes({ type: 'intentResult', requestId, status: 'error', message: 'Failed to save the theme.' })

    expect(container.querySelector<HTMLInputElement>('#appearance-save-theme-name')?.value).toBe('Harbor')
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to save the theme.')
    expect(buttonWithText('Save')?.disabled).toBe(false)
  })

  it('closes the save form on Cancel without contacting native', () => {
    emit(initEvent())
    openSaveThemeForm('Harbor')
    act(() => {
      buttonWithText('Cancel')!.click()
    })
    expect(container.querySelector('#appearance-save-theme-name')).toBeNull()
    expect(themesPostMessage.mock.calls.some((call) => call[0].type === 'saveTheme')).toBe(false)
  })

  it('confirms before deleting and leaves the current colors untouched after deletion', async () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [HARBOR_THEME] })
    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Delete theme Harbor"]')!.click()
    })
    expect(container.querySelector('[aria-label="Confirm deleting Harbor"]')).not.toBeNull()
    expect(themesPostMessage.mock.calls.some((call) => call[0].type === 'deleteTheme')).toBe(false)

    await new Promise((resolve) => window.requestAnimationFrame(resolve))
    const previewCountBefore = previewDraftCallCount()
    act(() => {
      container.querySelector<HTMLButtonElement>('.appearance-theme-delete-confirm-button')!.click()
    })
    const deleteCall = themesPostMessage.mock.calls.find((call) => call[0].type === 'deleteTheme')!
    expect(deleteCall[0].themeId).toBe(HARBOR_THEME.id)

    emitThemes({ type: 'snapshot', themes: [] })
    emitThemes({ type: 'intentResult', requestId: deleteCall[0].requestId, status: 'success' })
    await new Promise((resolve) => window.requestAnimationFrame(resolve))

    expect(container.querySelector('[aria-label="Confirm deleting Harbor"]')).toBeNull()
    expect(container.querySelector('.appearance-preset-swatch[aria-label="Harbor"]')).toBeNull()
    expect(previewDraftCallCount()).toBe(previewCountBefore)
    expect(container.querySelector<HTMLButtonElement>('button.primary-button')!.disabled).toBe(true)
  })

  it('keeps the confirmation open with the native error when deletion fails, and Cancel dismisses it', () => {
    emit(initEvent())
    emitThemes({ type: 'init', protocolVersion: 1, themes: [HARBOR_THEME] })
    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Delete theme Harbor"]')!.click()
    })
    act(() => {
      container.querySelector<HTMLButtonElement>('.appearance-theme-delete-confirm-button')!.click()
    })
    const requestId = themesPostMessage.mock.calls.find((call) => call[0].type === 'deleteTheme')![0].requestId as string
    emitThemes({ type: 'intentResult', requestId, status: 'error', message: 'Failed to delete the theme.' })

    expect(container.querySelector('[aria-label="Confirm deleting Harbor"] [role="alert"]')?.textContent).toBe('Failed to delete the theme.')
    act(() => {
      container.querySelector<HTMLButtonElement>('[aria-label="Confirm deleting Harbor"] .secondary-button')!.click()
    })
    expect(container.querySelector('[aria-label="Confirm deleting Harbor"]')).toBeNull()
    expect(container.querySelector('.appearance-preset-swatch[aria-label="Harbor"]')).not.toBeNull()
  })

  it('shows a load error while keeping the built-in presets usable', () => {
    emit(initEvent())
    emitThemes({ type: 'loadError', message: 'Failed to load saved themes.' })
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Failed to load saved themes.')
    expect(container.querySelector('[aria-label="Precursor"]')).not.toBeNull()
  })

  it('disables Save as Theme and explains why once 24 themes exist', () => {
    emit(initEvent())
    const themes = Array.from({ length: 24 }, (_, index) => ({
      ...HARBOR_THEME,
      id: `custom-${index.toString(16).padStart(32, '0')}`,
      name: `Theme ${index}`,
    }))
    emitThemes({ type: 'init', protocolVersion: 1, themes })
    expect(buttonWithText('Save as Theme')?.disabled).toBe(true)
    expect(container.querySelector('.appearance-save-theme-hint')?.textContent).toBe(
      'You can save up to 24 custom themes. Delete one to save another.',
    )
  })
})
