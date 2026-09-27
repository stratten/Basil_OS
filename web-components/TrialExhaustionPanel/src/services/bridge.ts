import type { FontConfig, InitMessage, SwiftMessage, ThemeConfig, UseLocalModelsResult } from '../types'

export const trialExhaustionPanelBridgeProtocolVersion = 1

declare global {
  interface Window {
    webkit?: {
      messageHandlers?: {
        trialExhaustionPanelBridge?: {
          postMessage: (message: SwiftMessage & { protocolVersion: number }) => void
        }
      }
    }
    basilTrialExhaustionPanel?: {
      onInit: (config: InitMessage) => void
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void
      onUseLocalModelsResult: (result: UseLocalModelsResult) => void
    }
  }
}

let initHandler: ((config: InitMessage) => void) | undefined
let themeHandler: ((theme: ThemeConfig, fonts: FontConfig) => void) | undefined
let useLocalModelsResultHandler: ((result: UseLocalModelsResult) => void) | undefined
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

export function registerUseLocalModelsResultHandler(handler: (result: UseLocalModelsResult) => void) {
  useLocalModelsResultHandler = handler
}

window.basilTrialExhaustionPanel = {
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
  onUseLocalModelsResult(result) {
    useLocalModelsResultHandler?.(result)
  },
}

function postToSwift(message: SwiftMessage) {
  window.webkit?.messageHandlers?.trialExhaustionPanelBridge?.postMessage({
    ...message,
    protocolVersion: trialExhaustionPanelBridgeProtocolVersion,
  })
}

export function notifyRendererReady() {
  postToSwift({ type: 'rendererReady' })
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height })
}

export function dismissPanel() {
  postToSwift({ type: 'dismiss' })
}

export function requestSignUp() {
  postToSwift({ type: 'signUp' })
}

export function requestAddOwnKeys() {
  postToSwift({ type: 'addOwnKeys' })
}

export function requestUseLocalModels(requestId: string) {
  postToSwift({ type: 'useLocalModels', requestId })
}
