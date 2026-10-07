import { createSwiftBridge, missingHandlerLogger } from '@shared/swiftBridge';
import type { FontConfig, ReconciliationConfig, ThemeConfig } from '../types';
import { applyHostFonts, applyHostTheme } from '../app/themeBootstrap';

// Messages posted back to the native host (window close / minimize / collapse / expand).
type SwiftMessage =
  | { action: 'close' }
  | { action: 'minimize' }
  | { action: 'collapse' }
  | { action: 'expand' };

declare global {
  interface Window {
    basilReconciliationConfig?: ReconciliationConfig;
    basilReconciliation?: {
      onInit: (config: ReconciliationConfig) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
    };
  }
}

let initCallback: ((config: ReconciliationConfig) => void) | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;
let pendingInit: ReconciliationConfig | null = window.basilReconciliationConfig ?? null;

export function registerInitHandler(callback: (config: ReconciliationConfig) => void) {
  initCallback = callback;
  if (pendingInit) {
    callback(pendingInit);
    pendingInit = null;
  }
}

export function registerThemeHandler(callback: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeCallback = callback;
}

export function applyConfigTheme(config: ReconciliationConfig) {
  if (config.theme) applyHostTheme(config.theme);
  if (config.fonts) applyHostFonts(config.fonts);
}

export function closeWorkspace() {
  postToSwift({ action: 'close' });
}

export function minimizeWorkspace() {
  postToSwift({ action: 'minimize' });
}

export function collapseWorkspace() {
  postToSwift({ action: 'collapse' });
}

export function expandWorkspace() {
  postToSwift({ action: 'expand' });
}

const swiftBridge = createSwiftBridge<SwiftMessage>('basilReconciliation', {
  onMissing: missingHandlerLogger('log', '[ReconciliationBridge] No Swift handler, message:'),
});

function postToSwift(message: SwiftMessage) {
  swiftBridge.post(message);
}

window.basilReconciliation = {
  onInit: (config: ReconciliationConfig) => {
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
    applyConfigTheme(config);
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => {
    applyHostTheme(theme);
    applyHostFonts(fonts);
    themeCallback?.(theme, fonts);
  },
};
