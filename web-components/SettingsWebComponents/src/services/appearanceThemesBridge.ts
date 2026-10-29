import { postToSwiftHandler } from '@shared/swiftBridge'
import type { AppearanceThemesNativeEvent, CustomAppearanceThemeInput } from '../types'

type OutgoingAppearanceThemesMessage =
  | { type: 'reactReady'; protocolVersion: 1 }
  | { type: 'saveTheme'; requestId: string; theme: CustomAppearanceThemeInput }
  | { type: 'deleteTheme'; requestId: string; themeId: string }

declare global {
  interface Window {
    basilAppearanceThemes?: {
      onEvent: (event: AppearanceThemesNativeEvent) => void
    }
  }
}

type EventHandler = (event: AppearanceThemesNativeEvent) => void

let queuedEvents: AppearanceThemesNativeEvent[] = []
let liveHandler: EventHandler | null = null

function dispatch(event: AppearanceThemesNativeEvent) {
  if (liveHandler) {
    liveHandler(event)
    return
  }
  queuedEvents.push(event)
}

window.basilAppearanceThemes = { onEvent: dispatch }

export function onAppearanceThemesEvent(handler: EventHandler): () => void {
  liveHandler = handler
  const events = queuedEvents
  queuedEvents = []
  events.forEach((event) => handler(event))
  return () => {
    if (liveHandler === handler) liveHandler = null
  }
}

function postMessage(message: OutgoingAppearanceThemesMessage) {
  postToSwiftHandler('basilAppearanceThemesBridge', message)
}

function requestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function notifyAppearanceThemesReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

export function saveAppearanceTheme(theme: CustomAppearanceThemeInput): string {
  const id = requestId('saveTheme')
  postMessage({ type: 'saveTheme', requestId: id, theme })
  return id
}

export function deleteAppearanceTheme(themeId: string): string {
  const id = requestId('deleteTheme')
  postMessage({ type: 'deleteTheme', requestId: id, themeId })
  return id
}
