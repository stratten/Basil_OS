import { createSwiftBridge, missingHandlerLogger } from '@shared/swiftBridge';
import type { FontConfig, ProfileEditorConfig, ThemeConfig } from '../types';
import { applyHostFonts, applyHostTheme } from '../app/themeBootstrap';

type SwiftMessage =
  | { action: 'saved'; didChange: boolean }
  | { action: 'declined'; didChange: boolean }
  | { action: 'close'; didChange: boolean }
  | { action: 'minimize' }
  | { action: 'openSourceTask'; taskId: string };

declare global {
  interface Window {
    basilProfileEditorConfig?: ProfileEditorConfig;
    basilProfileEditor?: {
      onInit: (config: ProfileEditorConfig) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
    };
  }
}

let initCallback: ((config: ProfileEditorConfig) => void) | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;
let pendingInit: ProfileEditorConfig | null = window.basilProfileEditorConfig ?? null;

export function registerInitHandler(callback: (config: ProfileEditorConfig) => void) {
  initCallback = callback;
  if (pendingInit) {
    callback(pendingInit);
    pendingInit = null;
  }
}

export function registerThemeHandler(callback: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeCallback = callback;
}

export function applyPreviewTheme(theme?: ThemeConfig, fonts?: FontConfig) {
  applyHostTheme(theme);
  applyHostFonts(fonts);
  const root = document.documentElement;
  if (theme?.primary) root.style.setProperty('--accent', theme.primary);
  if (fonts?.fontFamily) root.style.setProperty('--font-family-regular', fonts.fontFamily);
}

export function closeEditor() {
  postToSwift({ action: 'close', didChange: false });
}

export function minimizeEditor() {
  postToSwift({ action: 'minimize' });
}

export function notifySaved(didChange = true) {
  postToSwift({ action: 'saved', didChange });
}

export function notifyDeclined() {
  postToSwift({ action: 'declined', didChange: true });
}

export function openSourceTask(taskId: string) {
  postToSwift({ action: 'openSourceTask', taskId });
}

const swiftBridge = createSwiftBridge<SwiftMessage>('basilProfileEditor', {
  onMissing: missingHandlerLogger('log', '[ProfileEditorBridge] No Swift handler, message:'),
});

function postToSwift(message: SwiftMessage) {
  swiftBridge.post(message);
}

window.basilProfileEditor = {
  onInit: (config: ProfileEditorConfig) => {
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
    applyPreviewTheme(config.theme, config.fonts);
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => {
    applyPreviewTheme(theme, fonts);
    themeCallback?.(theme, fonts);
  },
};
