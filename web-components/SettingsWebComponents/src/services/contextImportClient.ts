import { createContextImportClient } from '@shared/contextImportClient'

declare global {
  interface Window {
    basilSettingsConfig?: { apiBaseUrl?: string }
  }
}

/** The import talks to the local backend directly, at the address the app injects into this page. */
export function settingsContextImportClient() {
  return createContextImportClient(window.basilSettingsConfig?.apiBaseUrl ?? '')
}
