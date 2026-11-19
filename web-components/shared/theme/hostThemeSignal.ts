/** Set on the document element once the host's theme has been applied to the page, so shared behavior that depends on the real colors (the blueprint reveal measures what paints) can wait for it. */
export const HOST_THEME_APPLIED_ATTRIBUTE = 'data-basil-theme-applied';
/** Dispatched on the window each time the host's theme is applied. */
export const HOST_THEME_APPLIED_EVENT = 'basil-theme-applied';

/** Records that the host's theme is now applied. Every surface's theme bootstrap calls this after it sets its colors. */
export function markHostThemeApplied(): void {
  if (typeof document === 'undefined') return;
  document.documentElement.setAttribute(HOST_THEME_APPLIED_ATTRIBUTE, 'true');
  window.dispatchEvent(new Event(HOST_THEME_APPLIED_EVENT));
}

export function isHostThemeApplied(): boolean {
  return typeof document !== 'undefined' && document.documentElement.getAttribute(HOST_THEME_APPLIED_ATTRIBUTE) === 'true';
}
