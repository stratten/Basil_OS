import { createSwiftBridge } from '@shared/swiftBridge'
import type { FontConfig, HotkeyMap, InitMessage, SwiftMessage, ThemeConfig } from '../types'

export const powerUserGuidePanelBridgeProtocolVersion = 1

declare global {
  interface Window {
    basilPowerUserGuidePanel?: {
      onInit: (config: InitMessage) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
      onHotkeysChanged: (update: { hotkeys: HotkeyMap }) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
let hotkeysHandler: ((hotkeys: HotkeyMap) => void) | undefined
let pendingInit: InitMessage | undefined

export function registerInitHandler(handler: (config: InitMessage) => void) {
  initHandler = handler
  if (pendingInit) {
    handler(pendingInit)
    pendingInit = undefined
  }
}

export function registerThemeHandler(handler: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeHandler = handler
}

export function registerHotkeysHandler(handler: (hotkeys: HotkeyMap) => void) {
  hotkeysHandler = handler
}

window.basilPowerUserGuidePanel = {
  onInit(config) {
    if (initHandler) {
      initHandler(config)
      return
    }
    pendingInit = config
  },
  onThemeChanged(theme, fonts) {
    themeHandler?.(theme, fonts)
  },
  onHotkeysChanged(update) {
    hotkeysHandler?.(update.hotkeys ?? {})
  },
}

const swiftBridge = createSwiftBridge<SwiftMessage & { protocolVersion: number }>('powerUserGuidePanelBridge')

function postToSwift(message: SwiftMessage) {
  swiftBridge.post({
    ...message,
    protocolVersion: powerUserGuidePanelBridgeProtocolVersion,
  })
}

export function notifyRendererReady() {
  postToSwift({ type: 'rendererReady' })
}

export function dismissPanel() {
  postToSwift({ type: 'dismiss' })
}
