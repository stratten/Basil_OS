import type {
  AppearanceColorPickerRequest,
  AppearanceIntentName,
  AppearanceNativeEvent,
  AppearanceSettings,
} from '../types'

type OutgoingIntentMessage =
  | {
    type: Exclude<AppearanceIntentName, 'openColorPicker'> | 'reactReady'
    requestId?: string
    draft?: AppearanceSettings
    protocolVersion?: 1
  }
  | ({ type: 'openColorPicker' } & AppearanceColorPickerRequest)

declare global {
  interface Window {
    basilAppearanceSettings?: {
      onEvent: (event: AppearanceNativeEvent) => void
    }
  }
}

type EventHandler = (event: AppearanceNativeEvent) => void

let queuedEvents: AppearanceNativeEvent[] = []
const liveHandlers = new Set<EventHandler>()

function dispatch(event: AppearanceNativeEvent) {
  if (liveHandlers.size > 0) {
    liveHandlers.forEach((handler) => handler(event))
    return
  }
  queuedEvents.push(event)
}

window.basilAppearanceSettings = {
  onEvent: dispatch,
}

/**
 * Subscribe to native events. Two independent consumers rely on this
 * channel at once: the always-mounted host-theme sync (see
 * `useHostThemeSync`) and the Appearance & Format tab's own settings state,
 * which only mounts when that tab is selected. Both must receive every
 * broadcast, so this fans out to a set of handlers rather than a single
 * slot -- a single-slot design would let the later subscriber silently
 * evict the earlier one's callback on unmount. Event(s) that arrived before
 * any handler subscribed (queued by the module-level `dispatch` above,
 * which runs the moment this file is imported because it assigns
 * `window.basilAppearanceSettings` synchronously) are flushed to the first
 * subscriber, in order, before this function returns. Returns an
 * unsubscribe function.
 */
export function onAppearanceEvent(handler: EventHandler): () => void {
  liveHandlers.add(handler)
  if (queuedEvents.length > 0) {
    const toFlush = queuedEvents
    queuedEvents = []
    for (const event of toFlush) {
      handler(event)
    }
  }
  return () => {
    liveHandlers.delete(handler)
  }
}

function postMessage(message: OutgoingIntentMessage) {
  window.webkit?.messageHandlers?.basilAppearanceSettingsBridge?.postMessage(message)
}

export function notifyAppearanceSettingsReady() {
  postMessage({ type: 'reactReady', protocolVersion: 1 })
}

let pendingPreviewFrame: number | null = null
let latestPreviewDraft: AppearanceSettings | null = null

/**
 * Coalesce rapid color/font edits into at most one native `previewDraft`
 * message per animation frame. Only the most recent draft in a frame is
 * ever sent; intermediate drafts within the same frame are dropped.
 */
export function previewDraft(draft: AppearanceSettings) {
  latestPreviewDraft = draft
  if (pendingPreviewFrame !== null) {
    return
  }
  pendingPreviewFrame = window.requestAnimationFrame(() => {
    pendingPreviewFrame = null
    if (latestPreviewDraft) {
      postMessage({ type: 'previewDraft', draft: latestPreviewDraft })
    }
  })
}

function generateRequestId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function saveDraft(draft: AppearanceSettings): string {
  const requestId = generateRequestId('saveDraft')
  postMessage({ type: 'saveDraft', requestId, draft })
  return requestId
}

export function cancelDraft(): string {
  const requestId = generateRequestId('cancelDraft')
  postMessage({ type: 'cancelDraft', requestId })
  return requestId
}

export function resetDraft(): string {
  const requestId = generateRequestId('resetDraft')
  postMessage({ type: 'resetDraft', requestId })
  return requestId
}

export function openAppearanceColorPicker(request: AppearanceColorPickerRequest) {
  postMessage({ type: 'openColorPicker', ...request })
}

