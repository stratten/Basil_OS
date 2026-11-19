export const TEXT_SCALE_STEPS = [0.9, 1.0, 1.1, 1.25, 1.4] as const
export const DEFAULT_TEXT_SCALE = 1.0

interface AppearanceTextSizeControlProps {
  value: number
  onChange: (textScale: number) => void
}

export function textScaleLabel(step: number): string {
  return `${Math.round(step * 100)}%`
}

/** The step nearest to `value`, with a tie going to the smaller step, matching the backend and the native app. */
export function nearestTextScaleStep(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_TEXT_SCALE
  return TEXT_SCALE_STEPS.reduce((best, step) => (Math.abs(step - value) < Math.abs(best - value) ? step : best))
}

export function AppearanceTextSizeControl({ value, onChange }: AppearanceTextSizeControlProps) {
  const selected = nearestTextScaleStep(value)
  return (
    <div className="appearance-text-size">
      <div className="appearance-finish-toggle" role="group" aria-label="Text size">
        <span className="appearance-finish-label">Text size:</span>
        {TEXT_SCALE_STEPS.map((step) => (
          <button
            key={step}
            type="button"
            className={`appearance-text-size-option${selected === step ? ' is-selected' : ''}`}
            aria-pressed={selected === step}
            onClick={() => onChange(step)}
          >
            {textScaleLabel(step)}
          </button>
        ))}
        <button
          type="button"
          className="appearance-text-size-option appearance-text-size-reset"
          disabled={selected === DEFAULT_TEXT_SCALE}
          onClick={() => onChange(DEFAULT_TEXT_SCALE)}
        >
          Reset
        </button>
      </div>
      <p className="appearance-text-size-hint">Scales text in every Basil window, including this one. Choosing a size here previews it right away and is saved with the rest of your appearance changes. In any Basil window, press ⌘+ to enlarge the text, ⌘− to shrink it, and ⌘0 to return to 100%. Those shortcuts save the new size immediately, and windows that are already open update right away. While this page has unsaved changes they change the unsaved size instead, which is saved with the rest.</p>
    </div>
  )
}
