/** The download and delete glyphs the Custom Models rows already use (24px viewBox, `currentColor`, thin round strokes), so a local model's actions look the same wherever it is listed. Sizing and stroke come from the button class that hosts the icon. */
export function DownloadIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10M8 10l4 4 4-4M5 19h14" /></svg>
}

export function DeleteIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg>
}

/** One small outline glyph per fit state, so the badge never relies on color alone: a check, an exclamation mark, and a cross. */
export function ModelFitIcon({ kind }: { kind: 'comfortable' | 'tight' | 'too_large' }) {
  if (kind === 'comfortable') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.2 2.2 4.8-5" /></svg>
  if (kind === 'tight') return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M12 8v5M12 16.2v.1" /></svg>
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m9 9 6 6M15 9l-6 6" /></svg>
}
