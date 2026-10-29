import { createSwiftBridge } from '@shared/swiftBridge'
import type { FontConfig, InitMessage, StatusMessage, SwiftMessage, ThemeConfig } from '../types'

export const startupLoadingWindowBridgeProtocolVersion = 1

declare global {
  interface Window {
    basilStartupLoadingWindow?: {
      onInit: (config: InitMessage) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
      onStatus: (status: StatusMessage) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
let statusHandler: ((status: StatusMessage) => void) | undefined
let pendingInit: InitMessage | undefined
let pendingStatus: StatusMessage | undefined

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

export function registerStatusHandler(handler: (status: StatusMessage) => void) {
  statusHandler = handler
  if (pendingStatus) {
    handler(pendingStatus)
    pendingStatus = undefined
  }
}

window.basilStartupLoadingWindow = {
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
  onStatus(status) {
    if (statusHandler) {
      statusHandler(status)
      return
    }
    pendingStatus = status
  },
}

const swiftBridge = createSwiftBridge<SwiftMessage & { protocolVersion: number }>('startupLoadingWindowBridge')

function postToSwift(message: SwiftMessage) {
  swiftBridge.post({
    ...message,
    protocolVersion: startupLoadingWindowBridgeProtocolVersion,
  })
}

export function notifyRendererReady() {
  postToSwift({ type: 'rendererReady' })
}

export function notifyDrawnIn() {
  postToSwift({ type: 'drawnIn' })
}

export function closeWindow() {
  postToSwift({ type: 'close' })
}

export function minimizeWindow() {
  postToSwift({ type: 'minimize' })
}

export function collapseWindow() {
  postToSwift({ type: 'collapse' })
}

export function expandWindow() {
  postToSwift({ type: 'expand' })
}
