import type { FontConfig, InitMessage, SwiftMessage, ThemeConfig } from '../types'

export const powerUserGuidePanelBridgeProtocolVersion = 1

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        powerUserGuidePanelBridge?: {
          postMessage: (message: SwiftMessage & { protocolVersion: number }) => void
        }
      }
    }
    basilPowerUserGuidePanel?: {
      onInit: (config: InitMessage) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
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
}

function postToSwift(message: SwiftMessage) {
  window.webkit?.messageHandlers?.powerUserGuidePanelBridge?.postMessage({
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
