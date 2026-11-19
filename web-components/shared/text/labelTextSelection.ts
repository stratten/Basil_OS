import type { MouseEvent } from 'react'

/**
 * Click handler for a `<label>` that wraps a checkbox and also holds text people may want to select.
 * Releasing the mouse after selecting that text clicks the label, which would otherwise toggle the checkbox.
 * A click on the checkbox itself, or a selection that is somewhere else on the page, is left alone.
 */
export function ignoreLabelClickWhileSelectingText(event: MouseEvent<HTMLLabelElement>) {
  if (event.target instanceof HTMLInputElement) return
  const selection = window.getSelection()
  if (!selection || selection.isCollapsed || selection.toString().trim() === '') return
  const label = event.currentTarget
  if (label.contains(selection.anchorNode) || label.contains(selection.focusNode)) event.preventDefault()
}
