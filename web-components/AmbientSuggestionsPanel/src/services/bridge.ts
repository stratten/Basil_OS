import type { AnchorRect, AmbientRuntimeStatus, AmbientSuggestion, EvaluationModel, FontConfig, InitMessage, SwiftMessage, ThemeConfig } from '../types';

declare global {
  interface Window {
    webkit?: {
      messageHandlers: {
        ambientSuggestionsBridge: {
          postMessage: (message: SwiftMessage) => void;
        };
        ambientSuggestionsLog?: {
          postMessage: (message: { level: string; message: string }) => void;
        };
      };
    };
    basilAmbientSuggestions?: {
      onInit: (config: InitMessage) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
      upsertSuggestion: (suggestion: AmbientSuggestion) => void;
      removeSuggestion: (suggestionId: string) => void;
      statusChanged: (status: AmbientRuntimeStatus) => void;
      modelSelected: (modelId: string) => void;
    };
  }
}

let initCallback: ((config: InitMessage) => void) | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;
let upsertCallback: ((suggestion: AmbientSuggestion) => void) | null = null;
let removeCallback: ((suggestionId: string) => void) | null = null;
let statusCallback: ((status: AmbientRuntimeStatus) => void) | null = null;
let modelSelectedCallback: ((modelId: string) => void) | null = null;

let pendingInit: InitMessage | null = null;
const pendingSuggestions = new Map<string, AmbientSuggestion>();
let pendingStatus: AmbientRuntimeStatus | null = null;

export function registerInitHandler(cb: (config: InitMessage) => void) {
  initCallback = cb;
  if (pendingInit) {
    cb(pendingInit);
    pendingInit = null;
  }
}

export function registerThemeHandler(cb: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeCallback = cb;
}

export function registerSuggestionHandlers(
  upsert: (suggestion: AmbientSuggestion) => void,
  remove: (suggestionId: string) => void
) {
  upsertCallback = upsert;
  removeCallback = remove;
  for (const suggestion of pendingSuggestions.values()) {
    upsert(suggestion);
  }
  pendingSuggestions.clear();
}

export function registerStatusHandler(cb: (status: AmbientRuntimeStatus) => void) {
  statusCallback = cb;
  if (pendingStatus) {
    cb(pendingStatus);
    pendingStatus = null;
  }
}

export function registerModelSelectionHandler(cb: (modelId: string) => void) {
  modelSelectedCallback = cb;
}

window.basilAmbientSuggestions = {
  onInit: (config: InitMessage) => {
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => themeCallback?.(theme, fonts),
  upsertSuggestion: (suggestion: AmbientSuggestion) => {
    if (upsertCallback) {
      upsertCallback(suggestion);
    } else {
      pendingSuggestions.set(suggestion.suggestion_id, suggestion);
    }
  },
  removeSuggestion: (suggestionId: string) => {
    pendingSuggestions.delete(suggestionId);
    removeCallback?.(suggestionId);
  },
  statusChanged: (status: AmbientRuntimeStatus) => {
    if (statusCallback) {
      statusCallback(status);
    } else {
      pendingStatus = status;
    }
  },
  modelSelected: (modelId: string) => {
    modelSelectedCallback?.(modelId);
  },
};

function postToSwift(message: SwiftMessage) {
  if (window.webkit?.messageHandlers.ambientSuggestionsBridge) {
    window.webkit.messageHandlers.ambientSuggestionsBridge.postMessage(message);
  } else {
    console.log('[AmbientSuggestionsBridge] No Swift handler, message:', message);
  }
}

export function acceptSuggestion(suggestionId: string) {
  postToSwift({ type: 'acceptSuggestion', suggestionId });
}

export function rejectSuggestion(suggestionId: string) {
  postToSwift({ type: 'rejectSuggestion', suggestionId });
}

export function dismissPanel() {
  postToSwift({ type: 'dismissPanel' });
}

export function minimizePanel() {
  postToSwift({ type: 'minimizePanel' });
}

export function toggleCollapsePanel(compactSize?: { width: number; height: number }) {
  postToSwift({ type: 'toggleCollapsePanel', compactSize });
}

export function notifyAmbientRuntimeChanged() {
  postToSwift({ type: 'ambientRuntimeChanged' });
}

export function notifyAmbientPanelReady() {
  postToSwift({ type: 'ambientPanelReady' });
}

export function requestResize(width: number, height: number) {
  postToSwift({ type: 'requestResize', width, height });
}

export function requestModelPicker(models: EvaluationModel[], selectedModelId: string, anchorRect: AnchorRect) {
  postToSwift({ type: 'showModelPicker', models, selectedModelId, anchorRect });
}

export function logAmbientPanel(level: 'log' | 'warn' | 'error', message: string) {
  if (window.webkit?.messageHandlers.ambientSuggestionsLog) {
    window.webkit.messageHandlers.ambientSuggestionsLog.postMessage({ level, message });
  } else if (level === 'error') {
    console.error(message);
  } else if (level === 'warn') {
    console.warn(message);
  } else {
    console.log(message);
  }
}
