import {
  createFilePreviewRequestManager,
  type ArtifactPreviewTransport,
  type FilePreviewPayload,
} from '@agent-task/components/artifacts/transport/artifactPreviewTransport';
import { postBridgeMessage } from './bridge';
import { hasSwiftHandler } from '@shared/swiftBridge';

let filePreviewReadyCallback: ((payload: FilePreviewPayload) => void) | null = null;
let filePreviewUpdatedCallback: ((payload: FilePreviewPayload) => void) | null = null;
let filePreviewAvailabilityRequestCounter = 0;
const pendingFilePreviewAvailabilityRequests = new Map<
  string,
  { resolve: (paths: Set<string>) => void; reject: (error: Error) => void; timeoutId: ReturnType<typeof setTimeout> }
>();

window.basilBoardBridge = {
  ...window.basilBoardBridge,
  onFilePreviewReady: (payload) => filePreviewReadyCallback?.(payload),
  onFilePreviewUpdated: (payload) => filePreviewUpdatedCallback?.(payload),
  onFilePreviewAvailability: (payload) => {
    const pending = pendingFilePreviewAvailabilityRequests.get(payload.requestId);
    if (!pending) return;
    clearTimeout(pending.timeoutId);
    pendingFilePreviewAvailabilityRequests.delete(payload.requestId);
    pending.resolve(new Set(payload.availablePaths));
  },
};

export function createBoardArtifactPreviewTransport(): ArtifactPreviewTransport {
  return createFilePreviewRequestManager(
    (message) => {
      const { type, ...rest } = message;
      postBridgeMessage(type, rest);
    },
    (cb) => {
      filePreviewReadyCallback = cb;
      return () => {
        if (filePreviewReadyCallback === cb) filePreviewReadyCallback = null;
      };
    },
    (cb) => {
      filePreviewUpdatedCallback = cb;
      return () => {
        if (filePreviewUpdatedCallback === cb) filePreviewUpdatedCallback = null;
      };
    },
  );
}

export function openConversationArtifactFile(path: string): void {
  postBridgeMessage('openFile', { path });
}

export function openConversationArtifactContainingFolder(path: string): void {
  postBridgeMessage('openContainingFolder', { path });
}

export function openConversationArtifactPreviewWindow(path: string): void {
  postBridgeMessage('openFilePreviewWindow', { path });
}

function buildConversationLocalPreviewTargetUrl(path: string): string {
  return path.startsWith('http')
    ? path
    : `file://${path.split('/').map(segment => encodeURIComponent(segment)).join('/')}`;
}

export function openConversationStaticLocalWebPreview(path: string, agentTaskId: string, artifactId: string): void {
  postBridgeMessage('openLocalWebPreview', {
    mode: 'static',
    targetUrl: buildConversationLocalPreviewTargetUrl(path),
    artifactId,
    agentTaskId,
    displayName: path.split('/').pop() ?? 'Preview',
  });
}

export function openConversationLocalServerPreview(path: string, agentTaskId: string, artifactId: string): void {
  postBridgeMessage('openLocalWebPreview', {
    mode: 'devServer',
    targetUrl: buildConversationLocalPreviewTargetUrl(path),
    artifactId,
    agentTaskId,
    displayName: path.split('/').pop() ?? 'Preview',
  });
}

export function checkConversationArtifactPreviewAvailability(paths: string[]): Promise<Set<string>> {
  const uniquePaths = [...new Set(paths)];
  if (uniquePaths.length === 0) return Promise.resolve(new Set());
  if (!hasSwiftHandler('basilBoardBridge')) return Promise.resolve(new Set(uniquePaths));

  const requestId = `board-file-preview-availability-${Date.now()}-${++filePreviewAvailabilityRequestCounter}`;
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      pendingFilePreviewAvailabilityRequests.delete(requestId);
      reject(new Error('File preview availability request timed out.'));
    }, 5000);
    pendingFilePreviewAvailabilityRequests.set(requestId, { resolve, reject, timeoutId });
    postBridgeMessage('checkFilePreviewAvailability', { requestId, paths: uniquePaths });
  });
}
