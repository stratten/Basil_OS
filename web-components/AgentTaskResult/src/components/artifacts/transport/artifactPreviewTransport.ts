export type FilePreviewKind = 'markdown' | 'text' | 'code' | 'htmlSource' | 'pdf' | 'unsupported';

export interface FilePreviewPayload {
  requestId: string;
  path: string;
  name: string;
  kind: FilePreviewKind;
  content?: string;
  error?: string;
}

export interface InlineNativePreviewFrame {
  left: number;
  top: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
}

export type FilePreviewOutgoingMessage =
  | { type: 'previewFile'; requestId: string; path: string }
  | { type: 'clearFilePreview'; requestId: string }
  | { type: 'setInlineNativePreviewFrame'; requestId: string; frame: InlineNativePreviewFrame }
  | { type: 'hideInlineNativePreview'; requestId: string }
  | { type: 'clearInlineNativePreview'; requestId: string };

export interface ArtifactPreviewTransport {
  previewFile(path: string): Promise<FilePreviewPayload>;
  clearFilePreview(requestId: string): void;
  registerFilePreviewUpdateHandler(cb: (payload: FilePreviewPayload) => void): () => void;
  setInlineNativePreviewFrame(requestId: string, frame: InlineNativePreviewFrame): void;
  hideInlineNativePreview(requestId: string): void;
  clearInlineNativePreview(requestId: string): void;
}

const FILE_PREVIEW_TIMEOUT_MS = 10000;

interface PendingFilePreviewRequest {
  resolve: (payload: FilePreviewPayload) => void;
  reject: (error: Error) => void;
  timeoutId: ReturnType<typeof setTimeout>;
}

/**
 * Builds one host-agnostic file-preview transport. Each host (the Agent
 * Task webview, the Basil Board webview) supplies its own `postMessage`
 * (wraps that host's native-bridge post call) and its own `registerReady`/
 * `registerUpdated` (wrap that host's single global `onFilePreviewReady`/
 * `onFilePreviewUpdated` callback slot). The manager owns request IDs, the
 * ten-second timeout, and the one active update-handler slot so neither
 * host has to re-implement that bookkeeping.
 */
export function createFilePreviewRequestManager(
  postMessage: (message: FilePreviewOutgoingMessage) => void,
  registerReady: (cb: (payload: FilePreviewPayload) => void) => () => void,
  registerUpdated: (cb: (payload: FilePreviewPayload) => void) => () => void,
): ArtifactPreviewTransport {
  let requestCounter = 0;
  const pendingRequests = new Map<string, PendingFilePreviewRequest>();
  let updateHandler: ((payload: FilePreviewPayload) => void) | null = null;

  registerReady((payload) => {
    const pending = pendingRequests.get(payload.requestId);
    if (!pending) return;
    clearTimeout(pending.timeoutId);
    pendingRequests.delete(payload.requestId);
    pending.resolve(payload);
  });

  registerUpdated((payload) => {
    updateHandler?.(payload);
  });

  function previewFile(path: string): Promise<FilePreviewPayload> {
    const requestId = `file-preview-${Date.now()}-${++requestCounter}`;
    for (const [pendingRequestId, pending] of pendingRequests) {
      clearTimeout(pending.timeoutId);
      pendingRequests.delete(pendingRequestId);
      pending.reject(new Error('File preview request was superseded by a new request.'));
    }
    return new Promise((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        pendingRequests.delete(requestId);
        reject(new Error('File preview request timed out.'));
      }, FILE_PREVIEW_TIMEOUT_MS);
      pendingRequests.set(requestId, { resolve, reject, timeoutId });
      postMessage({ type: 'previewFile', requestId, path });
    });
  }

  function clearFilePreview(requestId: string): void {
    const pending = pendingRequests.get(requestId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      pendingRequests.delete(requestId);
      pending.reject(new Error('File preview request was cleared.'));
    }
    postMessage({ type: 'clearFilePreview', requestId });
  }

  function registerFilePreviewUpdateHandler(cb: (payload: FilePreviewPayload) => void): () => void {
    updateHandler = cb;
    return () => {
      if (updateHandler === cb) updateHandler = null;
    };
  }

  function setInlineNativePreviewFrame(requestId: string, frame: InlineNativePreviewFrame): void {
    postMessage({ type: 'setInlineNativePreviewFrame', requestId, frame });
  }

  function hideInlineNativePreview(requestId: string): void {
    postMessage({ type: 'hideInlineNativePreview', requestId });
  }

  function clearInlineNativePreview(requestId: string): void {
    postMessage({ type: 'clearInlineNativePreview', requestId });
  }

  return {
    previewFile,
    clearFilePreview,
    registerFilePreviewUpdateHandler,
    setInlineNativePreviewFrame,
    hideInlineNativePreview,
    clearInlineNativePreview,
  };
}
