import type { CaptureInitMessage, CaptureInputMessage, CaptureModelPickerAnchorRect, CaptureModelPickerOption, CaptureSnapshot, FontConfig, ThemeConfig } from '../types';

declare global {
  interface Window {
    webkit?: {
      messageHandlers: {
        agentTaskCaptureBridge?: {
          postMessage: (message: CaptureInputMessage) => void;
        };
      };
    };
    basilAgentTaskCapture?: {
      onInit: (payload: CaptureInitMessage) => void;
      onSnapshot: (snapshot: CaptureSnapshot) => void;
      onAudioLevel: (level: number, audioRevision: number) => void;
      onThemeChanged: (theme: ThemeConfig) => void;
      onFontsChanged: (fonts: FontConfig) => void;
    };
  }
}

let initCallback: ((payload: CaptureInitMessage) => void) | null = null;
let snapshotCallback: ((snapshot: CaptureSnapshot) => void) | null = null;
let audioLevelCallback: ((level: number, audioRevision: number) => void) | null = null;
let themeCallback: ((theme: ThemeConfig) => void) | null = null;
let fontsCallback: ((fonts: FontConfig) => void) | null = null;

// Monotonic-revision floor for `onSnapshot`, per
// `05_Bridge_Contract_And_Types.md` section 5.4. This is a defensive floor
// for the adversarial out-of-order/malformed case (Package 4 row L3), not an
// expected occurrence in normal operation, because WKWebView's
// `WKScriptMessageHandler` channel delivers messages in post order.
let lastSnapshotRevision = -1;

export function registerInitHandler(cb: (payload: CaptureInitMessage) => void) {
  initCallback = cb;
  return () => {
    if (initCallback === cb) initCallback = null;
  };
}

export function registerSnapshotHandler(cb: (snapshot: CaptureSnapshot) => void) {
  snapshotCallback = cb;
  return () => {
    if (snapshotCallback === cb) snapshotCallback = null;
  };
}

export function registerAudioLevelHandler(cb: (level: number, audioRevision: number) => void) {
  audioLevelCallback = cb;
  return () => {
    if (audioLevelCallback === cb) audioLevelCallback = null;
  };
}

export function registerThemeHandler(cb: (theme: ThemeConfig) => void) {
  themeCallback = cb;
  return () => {
    if (themeCallback === cb) themeCallback = null;
  };
}

export function registerFontsHandler(cb: (fonts: FontConfig) => void) {
  fontsCallback = cb;
  return () => {
    if (fontsCallback === cb) fontsCallback = null;
  };
}

window.basilAgentTaskCapture = {
  onInit: (payload: CaptureInitMessage) => {
    lastSnapshotRevision = payload.snapshot.revision;
    initCallback?.(payload);
  },
  onSnapshot: (snapshot: CaptureSnapshot) => {
    if (snapshot.revision <= lastSnapshotRevision) {
      console.warn(
        `[AgentTaskCaptureInput] Dropped out-of-order/stale onSnapshot (revision ${snapshot.revision} <= last-applied ${lastSnapshotRevision})`
      );
      return;
    }
    lastSnapshotRevision = snapshot.revision;
    snapshotCallback?.(snapshot);
  },
  onAudioLevel: (level: number, audioRevision: number) => {
    // Last-value-wins, no staleness rejection — see section 5.4 rationale.
    audioLevelCallback?.(level, audioRevision);
  },
  onThemeChanged: (theme: ThemeConfig) => themeCallback?.(theme),
  onFontsChanged: (fonts: FontConfig) => fontsCallback?.(fonts),
};

function postCaptureIntent(message: CaptureInputMessage) {
  if (window.webkit?.messageHandlers.agentTaskCaptureBridge) {
    window.webkit.messageHandlers.agentTaskCaptureBridge.postMessage(message);
  } else {
    console.log('[AgentTaskCaptureInput] No Swift handler, message:', message);
  }
}

export function sendCaptureInputReady() {
  postCaptureIntent({ type: 'captureInputReady' });
}

export function requestSnapshot() {
  postCaptureIntent({ type: 'requestSnapshot' });
}

export function requestCaptureResize(width: number, height: number) {
  postCaptureIntent({ type: 'requestCaptureResize', width, height });
}

export function reportCaptureHeaderExtent(height: number) {
  if (!Number.isFinite(height) || height <= 0) return;
  postCaptureIntent({ type: 'captureHeaderExtent', height });
}

export function enterVoiceMode() {
  postCaptureIntent({ type: 'enterVoiceMode' });
}

export function enterTextEntryMode() {
  postCaptureIntent({ type: 'enterTextEntryMode' });
}

export function updateTextDraft(text: string) {
  postCaptureIntent({ type: 'updateTextDraft', text });
}

export function submitTextPrompt(text: string, modelId?: string) {
  postCaptureIntent({ type: 'submitTextPrompt', text, modelId });
}

export function setSelectedModel(modelId: string | null) {
  postCaptureIntent({ type: 'setSelectedModel', modelId });
}

export function showNativeModelPicker(
  models: CaptureModelPickerOption[],
  selectedModelId: string | null,
  anchorRect: CaptureModelPickerAnchorRect,
) {
  postCaptureIntent({ type: 'showNativeModelPicker', models, selectedModelId, anchorRect });
}

export function cancelCapture() {
  postCaptureIntent({ type: 'cancelCapture' });
}

export function pickReferenceFiles() {
  postCaptureIntent({ type: 'pickReferenceFiles' });
}

export function removeReferencePath(index: number) {
  postCaptureIntent({ type: 'removeReferencePath', index });
}

export function openReferencePath(path: string) {
  postCaptureIntent({ type: 'openReferencePath', path });
}

export function showHistory() {
  postCaptureIntent({ type: 'showHistory' });
}
