import { useEffect, useRef, useState } from 'react'
import { AppearanceColorField } from '../components/AppearanceColorField'
import { AppearancePresetSwatches } from '../components/AppearancePresetSwatches'
import { AppearancePreviewCard } from '../components/AppearancePreviewCard'
import type { AppearancePreset } from '../data/appearancePresets'
import { AppearanceSaveBar } from '../components/AppearanceSaveBar'
import TokenizedSelect from '@shared/TokenizedSelect'
import {
  cancelDraft,
  notifyAppearanceSettingsReady,
  openAppearanceColorPicker,
  onAppearanceEvent,
  previewDraft,
  resetDraft,
  saveDraft,
} from '../services/bridge'
import { notifyDateTimeSettingsReady, onDateTimeEvent, updateDateDisplayStyle } from '../services/dateTimeBridge'
import { applyHostTheme } from '../services/hostTheme'
import type { AppearanceColorFieldId, AppearanceSettings, DateDisplayStyle } from '../types'

const DEFAULT_SETTINGS: AppearanceSettings = {
  backgroundColorRed: 0.0709251779736389,
  backgroundColorGreen: 0.10432000903519285,
  backgroundColorBlue: 0.22791699626277573,
  primaryColorRed: 0.21100852777444695,
  primaryColorGreen: 0.4699344845863317,
  primaryColorBlue: 0.8893695758678611,
  secondaryColorRed: 0.376,
  secondaryColorGreen: 0.647,
  secondaryColorBlue: 0.98,
  textColorRed: 0.9699399998499855,
  textColorGreen: 0.9902393003857255,
  textColorBlue: 1.0,
  surfaceFinish: 'flat',
  processingColorRed: 0.486,
  processingColorGreen: 0.227,
  processingColorBlue: 0.929,
  processingAccentColorRed: 0.867,
  processingAccentColorGreen: 0.839,
  processingAccentColorBlue: 0.996,
  preferredFont: 'Helvetica-Light',
}

function settingsEqual(a: AppearanceSettings, b: AppearanceSettings): boolean {
  return (Object.keys(a) as Array<keyof AppearanceSettings>).every((key) => a[key] === b[key])
}

function replacingColor(
  settings: AppearanceSettings,
  fieldId: AppearanceColorFieldId,
  red: number,
  green: number,
  blue: number,
): AppearanceSettings {
  switch (fieldId) {
    case 'background':
      return { ...settings, backgroundColorRed: red, backgroundColorGreen: green, backgroundColorBlue: blue }
    case 'primary':
      return { ...settings, primaryColorRed: red, primaryColorGreen: green, primaryColorBlue: blue }
    case 'secondary':
      return { ...settings, secondaryColorRed: red, secondaryColorGreen: green, secondaryColorBlue: blue }
    case 'text':
      return { ...settings, textColorRed: red, textColorGreen: green, textColorBlue: blue }
  }
}

function applyingPreset(settings: AppearanceSettings, preset: AppearancePreset): AppearanceSettings {
  return {
    ...settings,
    backgroundColorRed: preset.background.red,
    backgroundColorGreen: preset.background.green,
    backgroundColorBlue: preset.background.blue,
    primaryColorRed: preset.primary.red,
    primaryColorGreen: preset.primary.green,
    primaryColorBlue: preset.primary.blue,
    secondaryColorRed: preset.secondary.red,
    secondaryColorGreen: preset.secondary.green,
    secondaryColorBlue: preset.secondary.blue,
    textColorRed: preset.text.red,
    textColorGreen: preset.text.green,
    textColorBlue: preset.text.blue,
  }
}

type PendingOperation = 'save' | 'cancel' | null

function DateTimeSection() {
  const [dateDisplayStyle, setDateDisplayStyle] = useState<DateDisplayStyle | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const pendingRequestIdRef = useRef<string | null>(null)
  const confirmedDateDisplayStyleRef = useRef<DateDisplayStyle | null>(null)
  pendingRequestIdRef.current = pendingRequestId

  useEffect(() => {
    const unsubscribe = onDateTimeEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        confirmedDateDisplayStyleRef.current = event.dateDisplayStyle
        setDateDisplayStyle(event.dateDisplayStyle)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRequestIdRef.current) {
        pendingRequestIdRef.current = null
        setPendingRequestId(null)
        if (event.status === 'error') {
          setDateDisplayStyle(confirmedDateDisplayStyleRef.current)
          setErrorMessage(event.message ?? 'Failed to save the date display preference.')
        } else {
          setErrorMessage(null)
        }
      }
    })
    notifyDateTimeSettingsReady()
    return unsubscribe
  }, [])

  function handleChange(style: DateDisplayStyle) {
    if (pendingRequestIdRef.current) return
    setErrorMessage(null)
    const requestId = updateDateDisplayStyle(style)
    pendingRequestIdRef.current = requestId
    setPendingRequestId(requestId)
    setDateDisplayStyle(style)
  }

  return (
    <section className="appearance-settings-section">
      <h2>Date & Time</h2>
      {loadError ? (
        <p className="appearance-settings-status" role="alert">{loadError}</p>
      ) : dateDisplayStyle === null ? (
        <p className="appearance-settings-status" role="status">Loading date display preference...</p>
      ) : (
        <>
          <label htmlFor="appearance-date-display-select" className="appearance-font-label">Date Display:</label>
          <TokenizedSelect
            className="appearance-font-select"
            value={dateDisplayStyle}
            disabled={pendingRequestId !== null}
            ariaLabel="Date Display"
            onValueChange={(value) => handleChange(value as DateDisplayStyle)}
            options={[
              { value: 'relative', label: 'Relative (e.g. "2 hours ago")' },
              { value: 'absolute', label: 'Absolute (e.g. "Sep 4, 2026, 1:52 PM")' },
            ]}
          />
          {errorMessage && <p className="appearance-settings-status" role="alert">{errorMessage}</p>}
        </>
      )}
    </section>
  )
}

export function AppearanceSettingsApp() {
  const [persisted, setPersisted] = useState<AppearanceSettings | null>(null)
  const [draft, setDraft] = useState<AppearanceSettings | null>(null)
  const [availableFonts, setAvailableFonts] = useState<readonly string[]>([])
  const [pendingOperation, setPendingOperation] = useState<PendingOperation>(null)
  const [pendingRequestId, setPendingRequestId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [pendingExternalSnapshot, setPendingExternalSnapshot] = useState<AppearanceSettings | null>(null)
  const persistedRef = useRef<AppearanceSettings | null>(persisted)
  const pendingRequestIdRef = useRef(pendingRequestId)

  persistedRef.current = persisted
  pendingRequestIdRef.current = pendingRequestId

  const hasUnsavedChanges = draft !== null && persisted !== null && !settingsEqual(draft, persisted)

  useEffect(() => {
    const unsubscribe = onAppearanceEvent((event) => {
      if (event.type === 'themeChanged') {
        applyHostTheme(event.theme, event.fonts)
        return
      }
      if (event.type === 'colorPicked') {
        setDraft((currentDraft) => {
          if (!currentDraft) return currentDraft
          const nextDraft = replacingColor(currentDraft, event.fieldId, event.red, event.green, event.blue)
          previewDraft(nextDraft)
          return nextDraft
        })
        return
      }
      if (event.type === 'init' || event.type === 'snapshot') {
        if (event.type === 'init') {
          applyHostTheme(event.theme, event.fonts)
        }
        setAvailableFonts(event.availableFonts)
        setPersisted(event.settings)
        setDraft((currentDraft) => {
          const isClean = currentDraft === null
            || persistedRef.current === null
            || settingsEqual(currentDraft, persistedRef.current)
            || settingsEqual(currentDraft, event.settings)
          if (isClean) {
            setPendingExternalSnapshot(null)
            return event.settings
          }
          setPendingExternalSnapshot(event.settings)
          return currentDraft
        })
        return
      }
      if (event.type === 'intentResult') {
        if (event.requestId !== pendingRequestIdRef.current) {
          return
        }
        setPendingOperation(null)
        setPendingRequestId(null)
        if (event.status === 'error') {
          setErrorMessage(event.message ?? 'The request could not be completed.')
        } else {
          setErrorMessage(null)
        }
      }
    })
    notifyAppearanceSettingsReady()
    return unsubscribe
  }, [])

  function updateDraft(next: AppearanceSettings) {
    if (!draft || !persisted) return
    setDraft(next)
    previewDraft(next)
  }

  function handleSave() {
    if (!draft || pendingOperation) return
    setPendingOperation('save')
    setErrorMessage(null)
    const requestId = saveDraft(draft)
    pendingRequestIdRef.current = requestId
    setPendingRequestId(requestId)
  }

  function handleCancel() {
    if (!persisted || pendingOperation) return
    setPendingOperation('cancel')
    setErrorMessage(null)
    const requestId = cancelDraft()
    pendingRequestIdRef.current = requestId
    setPendingRequestId(requestId)
    setDraft(persisted)
  }

  function handleReset() {
    if (!draft || !persisted) return
    updateDraft(DEFAULT_SETTINGS)
    resetDraft()
  }

  function handleReloadExternalSnapshot() {
    if (!pendingExternalSnapshot) return
    setDraft(pendingExternalSnapshot)
    setPersisted(pendingExternalSnapshot)
    setPendingExternalSnapshot(null)
  }

  if (!draft || !persisted) {
    return (
      <div className="appearance-settings-shell">
        <p className="appearance-settings-status" role="status">Loading appearance settings...</p>
        <DateTimeSection />
      </div>
    )
  }

  return (
    <div className="appearance-settings-shell">
      {pendingExternalSnapshot && (
        <div className="appearance-external-change-banner" role="status">
          <span>Settings changed elsewhere.</span>
          <button type="button" className="secondary-button" onClick={handleReloadExternalSnapshot}>Reload</button>
        </div>
      )}

      <DateTimeSection />

      <section className="appearance-settings-section">
        <h2>Color Theme</h2>
        <AppearancePresetSwatches onSelect={(preset) => updateDraft(applyingPreset(draft, preset))} />
        <div className="appearance-finish-toggle" role="group" aria-label="Surface finish">
          <span className="appearance-finish-label">Finish:</span>
          <button
            type="button"
            className={`appearance-finish-option${draft.surfaceFinish === 'flat' ? ' is-selected' : ''}`}
            aria-pressed={draft.surfaceFinish === 'flat'}
            onClick={() => updateDraft({ ...draft, surfaceFinish: 'flat' })}
          >
            Flat
          </button>
          <button
            type="button"
            className={`appearance-finish-option${draft.surfaceFinish === 'metal' ? ' is-selected' : ''}`}
            aria-pressed={draft.surfaceFinish === 'metal'}
            onClick={() => updateDraft({ ...draft, surfaceFinish: 'metal' })}
          >
            Metallic
          </button>
        </div>
        <AppearanceColorField
          id="appearance-background-color"
          label="Background Color:"
          fieldId="background"
          red={draft.backgroundColorRed}
          green={draft.backgroundColorGreen}
          blue={draft.backgroundColorBlue}
          onRequestPicker={openAppearanceColorPicker}
        />
        <AppearanceColorField
          id="appearance-primary-color"
          label="Primary Color:"
          fieldId="primary"
          red={draft.primaryColorRed}
          green={draft.primaryColorGreen}
          blue={draft.primaryColorBlue}
          onRequestPicker={openAppearanceColorPicker}
        />
        <AppearanceColorField
          id="appearance-secondary-color"
          label="Secondary Color:"
          fieldId="secondary"
          red={draft.secondaryColorRed}
          green={draft.secondaryColorGreen}
          blue={draft.secondaryColorBlue}
          onRequestPicker={openAppearanceColorPicker}
        />
        <AppearanceColorField
          id="appearance-text-color"
          label="Text Color:"
          fieldId="text"
          red={draft.textColorRed}
          green={draft.textColorGreen}
          blue={draft.textColorBlue}
          onRequestPicker={openAppearanceColorPicker}
        />
      </section>

      <section className="appearance-settings-section">
        <h2>Typography</h2>
        <label className="appearance-font-label">Preferred Font:</label>
        <TokenizedSelect
          className="appearance-font-select"
          value={draft.preferredFont}
          ariaLabel="Preferred Font"
          onValueChange={(preferredFont) => updateDraft({ ...draft, preferredFont })}
          options={[
            ...(!availableFonts.includes(draft.preferredFont) ? [{ value: draft.preferredFont, label: draft.preferredFont }] : []),
            ...availableFonts.map((font) => ({ value: font, label: font })),
          ]}
        />
      </section>

      <section className="appearance-settings-section">
        <h2>Preview</h2>
        <AppearancePreviewCard draft={draft} />
      </section>

      <section className="appearance-settings-section">
        <AppearanceSaveBar
          hasUnsavedChanges={hasUnsavedChanges}
          isSaving={pendingOperation === 'save'}
          isCanceling={pendingOperation === 'cancel'}
          errorMessage={errorMessage}
          onSave={handleSave}
          onCancel={handleCancel}
          onReset={handleReset}
        />
      </section>
    </div>
  )
}
