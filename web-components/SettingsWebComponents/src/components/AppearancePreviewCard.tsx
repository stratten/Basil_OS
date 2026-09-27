import type { AppearanceSettings } from '../types'

function toCssColor(red: number, green: number, blue: number): string {
  return `rgb(${Math.round(red * 255)}, ${Math.round(green * 255)}, ${Math.round(blue * 255)})`
}

export function AppearancePreviewCard({ draft }: { draft: AppearanceSettings }) {
  const background = toCssColor(draft.backgroundColorRed, draft.backgroundColorGreen, draft.backgroundColorBlue)
  const primary = toCssColor(draft.primaryColorRed, draft.primaryColorGreen, draft.primaryColorBlue)
  const secondary = toCssColor(draft.secondaryColorRed, draft.secondaryColorGreen, draft.secondaryColorBlue)
  const text = toCssColor(draft.textColorRed, draft.textColorGreen, draft.textColorBlue)

  return (
    <div
      className="appearance-preview-card"
      style={{
        background,
        borderColor: primary,
        color: text,
        fontFamily: draft.preferredFont,
      }}
    >
      <h3 className="appearance-preview-headline" style={{ color: primary }}>Preview</h3>
      <p className="appearance-preview-body">This is how your selected font and colors will look throughout the application.</p>
      <div className="appearance-preview-buttons">
        <button type="button" className="appearance-preview-button-primary" style={{ background: primary }} disabled>Primary Button</button>
        <button type="button" className="appearance-preview-button-secondary" style={{ background: secondary }} disabled>Secondary Button</button>
        <button type="button" className="appearance-preview-button-bordered" style={{ borderColor: primary, color: primary }} disabled>Bordered</button>
      </div>
      <div className="appearance-preview-text-samples">
        <p className="appearance-preview-text-primary">Primary text color</p>
        <p className="appearance-preview-text-secondary">Secondary text (system gray)</p>
      </div>
    </div>
  )
}
