import { createSwiftBridge } from '@shared/swiftBridge';
import type { FontConfig, ThemeConfig } from '../../types';

export type LocalWebPreviewMode = 'static' | 'devServer';

export interface LocalWebPreviewInitMessage {
  mode: LocalWebPreviewMode;
  targetUrl: string;
  previewContentUrl?: string;
  artifactId: string;
  agentTaskId: string;
  /** Present when opened from the run detail tray; required to enable restore. */
  rootTaskId?: string;
  /**
   * The original source path this preview was opened for, stable across
   * `targetUrl` rewrites (dev-server session start rewrites `targetUrl` to
   * `session.url`, which is not a managed-history lookup key). Used to
   * query/select/restore managed versions.
   */
  canonicalPath?: string;
  displayName?: string;
  sessionId?: string;
  port?: number;
  wsUrl?: string;
  theme?: ThemeConfig;
  fonts?: FontConfig;
}

export interface LocalWebPreviewScreenshotPayload {
  path?: string;
  error?: string;
  capturedAt?: string;
}

export interface LocalWebPreviewConsoleEvidencePayload {
  text: string;
}

export interface LocalWebPreviewValidationFeedbackPayload {
  text: string;
}

export interface LocalWebPreviewValidationServerPayload {
  command: string;
  args: string[];
  cwd: string;
  port: number;
}

type LocalWebPreviewBridgeMessage =
  | { type: 'initAck' }
  | { type: 'closeWidget' }
  | { type: 'minimizeWidget' }
  | { type: 'openExternalUrl'; url: string }
  | { type: 'captureScreenshot' }
  | { type: 'getConsoleEvidence' }
  | { type: 'filePreviewChromeHeight'; height: number }
  | { type: 'previewWindowWillClose' }
  | { type: 'previewServerSessionStarted'; sessionId: string }
  | { type: 'previewServerSessionDenied'; sessionId: string; lastError?: string };

let initCallback: ((config: LocalWebPreviewInitMessage) => void) | null = null;
let consoleEvidenceCallback: ((payload: LocalWebPreviewConsoleEvidencePayload) => void) | null = null;
let validationFeedbackCallback: ((payload: LocalWebPreviewValidationFeedbackPayload) => void) | null = null;
let validationServerCallback: ((payload: LocalWebPreviewValidationServerPayload) => void) | null = null;
let pendingScreenshotRequest: ((payload: LocalWebPreviewScreenshotPayload) => void) | null = null;
let pendingConsoleEvidenceRequest: ((text: string) => void) | null = null;
let latestInitConfig: LocalWebPreviewInitMessage | null = null;

declare global {
  interface Window {
    basilLocalWebPreview?: {
      onInit: (config: LocalWebPreviewInitMessage) => void;
      onScreenshotCaptured: (payload: LocalWebPreviewScreenshotPayload) => void;
      onConsoleEvidence: (payload: LocalWebPreviewConsoleEvidencePayload) => void;
      onValidationFeedback: (payload: LocalWebPreviewValidationFeedbackPayload) => void;
      onValidationStartServer: (payload: LocalWebPreviewValidationServerPayload) => void;
    };
  }
}

window.basilLocalWebPreview = {
  onInit: (config) => {
    latestInitConfig = config;
    if (initCallback) {
      initCallback(config);
      window.setTimeout(() => postToNative({ type: 'initAck' }), 0);
    }
  },
  onScreenshotCaptured: (payload) => {
    pendingScreenshotRequest?.(payload);
    pendingScreenshotRequest = null;
  },
  onConsoleEvidence: (payload) => {
    consoleEvidenceCallback?.(payload);
    pendingConsoleEvidenceRequest?.(payload.text);
    pendingConsoleEvidenceRequest = null;
  },
  onValidationFeedback: (payload) => {
    validationFeedbackCallback?.(payload);
  },
  onValidationStartServer: (payload) => {
    validationServerCallback?.(payload);
  },
};

const swiftBridge = createSwiftBridge<LocalWebPreviewBridgeMessage>('localWebPreviewBridge');

function postToNative(message: LocalWebPreviewBridgeMessage) {
  swiftBridge.post(message);
}

export function registerLocalWebPreviewInitHandler(
  callback: (config: LocalWebPreviewInitMessage) => void,
): () => void {
  initCallback = callback;
  if (latestInitConfig) {
    callback(latestInitConfig);
    window.setTimeout(() => postToNative({ type: 'initAck' }), 0);
  }
  return () => {
    if (initCallback === callback) initCallback = null;
  };
}

export function registerConsoleEvidenceHandler(
  callback: (payload: LocalWebPreviewConsoleEvidencePayload) => void,
): () => void {
  consoleEvidenceCallback = callback;
  return () => {
    if (consoleEvidenceCallback === callback) consoleEvidenceCallback = null;
  };
}

export function registerLocalWebPreviewValidationFeedbackHandler(
  callback: (payload: LocalWebPreviewValidationFeedbackPayload) => void,
): () => void {
  validationFeedbackCallback = callback;
  return () => {
    if (validationFeedbackCallback === callback) validationFeedbackCallback = null;
  };
}

export function registerLocalWebPreviewValidationServerHandler(
  callback: (payload: LocalWebPreviewValidationServerPayload) => void,
): () => void {
  validationServerCallback = callback;
  return () => {
    if (validationServerCallback === callback) validationServerCallback = null;
  };
}

export function closeLocalWebPreviewWindow() {
  postToNative({ type: 'closeWidget' });
}

export function minimizeLocalWebPreviewWindow() {
  postToNative({ type: 'minimizeWidget' });
}

export function openExternalUrl(url: string) {
  postToNative({ type: 'openExternalUrl', url });
}

export function captureScreenshot(): Promise<LocalWebPreviewScreenshotPayload> {
  if (!swiftBridge.isAvailable()) {
    return Promise.resolve({});
  }
  return new Promise(resolve => {
    let complete: (payload: LocalWebPreviewScreenshotPayload) => void;
    const timeoutId = window.setTimeout(() => {
      if (pendingScreenshotRequest === complete) {
        pendingScreenshotRequest = null;
        resolve({});
      }
    }, 500);
    complete = (payload: LocalWebPreviewScreenshotPayload) => {
      window.clearTimeout(timeoutId);
      resolve(payload);
    };
    pendingScreenshotRequest = complete;
    postToNative({ type: 'captureScreenshot' });
  });
}

export function requestConsoleEvidence(): Promise<string> {
  return new Promise(resolve => {
    let complete: (text: string) => void;
    const timeoutId = window.setTimeout(() => {
      if (pendingConsoleEvidenceRequest === complete) {
        pendingConsoleEvidenceRequest = null;
        resolve('');
      }
    }, 500);
    complete = (text: string) => {
      window.clearTimeout(timeoutId);
      resolve(text);
    };
    pendingConsoleEvidenceRequest = complete;
    postToNative({ type: 'getConsoleEvidence' });
  });
}

export function reportLocalWebPreviewChromeHeight(height: number) {
  postToNative({ type: 'filePreviewChromeHeight', height });
}

export function notifyLocalWebPreviewWindowWillClose() {
  postToNative({ type: 'previewWindowWillClose' });
}

export function notifyLocalPreviewServerSessionStarted(sessionId: string) {
  postToNative({ type: 'previewServerSessionStarted', sessionId });
}

export function notifyLocalPreviewServerSessionDenied(sessionId: string, lastError?: string) {
  postToNative({ type: 'previewServerSessionDenied', sessionId, lastError });
}

export function readCurrentPreviewUrl(
  frame: HTMLIFrameElement | null,
  fallbackUrl: string,
): { url: string; status: 'current' | 'fallback' } {
  if (!frame) {
    return { url: fallbackUrl, status: 'fallback' };
  }
  try {
    const href = frame.contentWindow?.location.href;
    if (typeof href === 'string' && href.length > 0 && href !== 'about:blank') {
      return { url: href, status: 'current' };
    }
  } catch {
    // Cross-origin access throws a SecurityError; the loopback preview frame
    // is expected to be same-origin, so this only triggers on an unexpected
    // navigation and must fail safe to the last known-good URL.
  }
  return { url: fallbackUrl, status: 'fallback' };
}
