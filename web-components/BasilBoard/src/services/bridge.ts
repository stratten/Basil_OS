import type {
  AgentTaskOriginNavigationPayload,
  AgentTaskWidgetLaunchPayload,
  BasilBoardInitPayload,
  BoardAgentTasksAvailabilityPayload,
  BoardConversationAvailabilityPayload,
  BoardMeetingsAvailabilityPayload,
  ConversationVoiceCaptureFinishedPayload,
  ConversationVoiceCaptureStatePayload,
  DetachedConversationsChangedPayload,
  DetachedTabsChangedPayload,
  HomeVoiceCaptureFinishedPayload,
  HomeVoiceCaptureStatePayload,
  WidgetLaunchFailedPayload,
} from '../contracts';
import type { SwiftMessage } from '@agent-task/types';
import type { FilePreviewPayload } from '@agent-task/components/artifacts/transport/artifactPreviewTransport';
import { applyHostFonts, applyHostTheme } from '../theme/agentTaskTheme';

type InitHandler = (payload: BasilBoardInitPayload) => void;
type VoiceStateHandler = (payload: HomeVoiceCaptureStatePayload) => void;
type VoiceFinishedHandler = (payload: HomeVoiceCaptureFinishedPayload) => void;
type ConversationVoiceStateHandler = (payload: ConversationVoiceCaptureStatePayload) => void;
type ConversationVoiceFinishedHandler = (payload: ConversationVoiceCaptureFinishedPayload) => void;
type ConversationAttachmentErrorHandler = (message: string) => void;
type StatusIconHandler = (payload: { dataUrl: string }) => void;
type WidgetResultHandler = (payload: AgentTaskWidgetLaunchPayload) => void;
type WidgetFailedHandler = (payload: WidgetLaunchFailedPayload) => void;
type FilesPickedHandler = (paths: string[]) => void;
type ConversationFilesPickedHandler = (paths: string[]) => void;
type TodoWorkspaceFilesPickedHandler = (paths: string[]) => void;
type TodoReferenceFilesPickedHandler = (paths: string[]) => void;
type DetachedTabsChangedHandler = (payload: DetachedTabsChangedPayload) => void;
type DetachedConversationsChangedHandler = (payload: DetachedConversationsChangedPayload) => void;
type AgentTaskOriginNavigationHandler = (payload: AgentTaskOriginNavigationPayload) => void;

interface WorkspaceDirectoryPickedPayload {
  requestId: string;
  status: 'selected' | 'canceled' | 'error';
  path?: string;
  message?: string;
}

export type WorkspaceDirectoryPickResult =
  | { status: 'selected'; path: string }
  | { status: 'canceled' }
  | { status: 'error'; message: string };
type BoardAgentTasksAvailabilityHandler = (payload: BoardAgentTasksAvailabilityPayload) => void;
type BoardConversationAvailabilityHandler = (payload: BoardConversationAvailabilityPayload) => void;
type BoardMeetingsAvailabilityHandler = (payload: BoardMeetingsAvailabilityPayload) => void;

declare global {
  interface Window {
    webkit?: {
      messageHandlers: {
        agentTaskBridge?: {
          postMessage: (message: SwiftMessage) => void;
        };
        basilBoardBridge?: {
          postMessage: (message: Record<string, unknown>) => void;
        };
        localWebPreviewBridge?: {
          postMessage: (message: unknown) => void;
        };
      };
    };
    basilBoardBridge?: {
      onInit?: InitHandler;
      onThemeChanged?: (payload: {
        theme: BasilBoardInitPayload['theme'];
        fonts: BasilBoardInitPayload['fonts'];
      }) => void;
      onVoiceCaptureState?: VoiceStateHandler;
      onVoiceCaptureFinished?: VoiceFinishedHandler;
      onConversationVoiceCaptureState?: ConversationVoiceStateHandler;
      onConversationVoiceCaptureFinished?: ConversationVoiceFinishedHandler;
      onConversationAttachmentError?: (payload: { message: string }) => void;
      onStatusIconChanged?: StatusIconHandler;
      onOpenExistingWidgetResult?: WidgetResultHandler;
      onWidgetLaunchFailed?: WidgetFailedHandler;
      onFilesPicked?: (payload: { paths: string[] }) => void;
      onConversationFilesPicked?: (payload: { paths: string[] }) => void;
      onFocusConversationComposer?: () => void;
      onTodoWorkspaceFilesPicked?: (payload: { paths: string[] }) => void;
      onTodoReferenceFilesPicked?: (payload: { paths: string[] }) => void;
      onWorkspaceDirectoryPicked?: (payload: WorkspaceDirectoryPickedPayload) => void;
      onDetachedBoardTabsChanged?: DetachedTabsChangedHandler;
      onDetachedConversationsChanged?: DetachedConversationsChangedHandler;
      onNavigateToAgentTaskOrigin?: AgentTaskOriginNavigationHandler;
      onBoardAgentTasksAvailabilityChanged?: BoardAgentTasksAvailabilityHandler;
      onBoardConversationAvailabilityChanged?: BoardConversationAvailabilityHandler;
      onBoardMeetingsAvailabilityChanged?: BoardMeetingsAvailabilityHandler;
      onFilePreviewReady?: (payload: FilePreviewPayload) => void;
      onFilePreviewUpdated?: (payload: FilePreviewPayload) => void;
      onFilePreviewAvailability?: (payload: { requestId: string; availablePaths: string[] }) => void;
    };
  }
}

const pendingInit: BasilBoardInitPayload[] = [];
const pendingVoiceStates: HomeVoiceCaptureStatePayload[] = [];
const pendingVoiceFinished: HomeVoiceCaptureFinishedPayload[] = [];
const pendingConversationVoiceStates: ConversationVoiceCaptureStatePayload[] = [];
const pendingConversationVoiceFinished: ConversationVoiceCaptureFinishedPayload[] = [];
const pendingConversationAttachmentErrors: string[] = [];
const pendingStatusIcons: { dataUrl: string }[] = [];
const pendingFilesPicked: string[][] = [];
const pendingConversationFilesPicked: string[][] = [];
const pendingTodoWorkspaceFilesPicked: string[][] = [];
const pendingTodoReferenceFilesPicked: string[][] = [];
const pendingDetachedTabsChanged: DetachedTabsChangedPayload[] = [];
const pendingDetachedConversationsChanged: DetachedConversationsChangedPayload[] = [];
let pendingAgentTaskOriginNavigation: AgentTaskOriginNavigationPayload | null = null;
const pendingBoardAgentTasksAvailability: BoardAgentTasksAvailabilityPayload[] = [];
const pendingBoardConversationAvailability: BoardConversationAvailabilityPayload[] = [];
const pendingBoardMeetingsAvailability: BoardMeetingsAvailabilityPayload[] = [];

let initHandler: InitHandler | null = null;
let voiceStateHandler: VoiceStateHandler | null = null;
let voiceFinishedHandler: VoiceFinishedHandler | null = null;
let conversationVoiceStateHandler: ConversationVoiceStateHandler | null = null;
let conversationVoiceFinishedHandler: ConversationVoiceFinishedHandler | null = null;
let conversationAttachmentErrorHandler: ConversationAttachmentErrorHandler | null = null;
let statusIconHandler: StatusIconHandler | null = null;
let filesPickedHandler: FilesPickedHandler | null = null;
let conversationFilesPickedHandler: ConversationFilesPickedHandler | null = null;
let conversationComposerFocusHandler: (() => void) | null = null;
let pendingConversationComposerFocus = false;
let todoWorkspaceFilesPickedHandler: TodoWorkspaceFilesPickedHandler | null = null;
let todoReferenceFilesPickedHandler: TodoReferenceFilesPickedHandler | null = null;
let detachedTabsChangedHandler: DetachedTabsChangedHandler | null = null;
let detachedConversationsChangedHandler: DetachedConversationsChangedHandler | null = null;
let agentTaskOriginNavigationHandler: AgentTaskOriginNavigationHandler | null = null;
let boardAgentTasksAvailabilityHandler: BoardAgentTasksAvailabilityHandler | null = null;
let boardConversationAvailabilityHandler: BoardConversationAvailabilityHandler | null = null;
let boardMeetingsAvailabilityHandler: BoardMeetingsAvailabilityHandler | null = null;

let workspaceDirectoryPickRequestCounter = 0;
const pendingWorkspaceDirectoryPickRequests = new Map<
  string,
  {
    resolve: (result: WorkspaceDirectoryPickResult) => void;
    timeoutId: ReturnType<typeof setTimeout>;
  }
>();

function handleWorkspaceDirectoryPicked(payload: WorkspaceDirectoryPickedPayload): void {
  if (typeof payload?.requestId !== 'string' || payload.requestId.length === 0) {
    return;
  }
  const pending = pendingWorkspaceDirectoryPickRequests.get(payload.requestId);
  if (!pending) {
    return;
  }
  clearTimeout(pending.timeoutId);
  pendingWorkspaceDirectoryPickRequests.delete(payload.requestId);

  if (payload.status === 'canceled') {
    pending.resolve({ status: 'canceled' });
    return;
  }
  if (payload.status === 'selected' && typeof payload.path === 'string' && payload.path.trim().length > 0) {
    pending.resolve({ status: 'selected', path: payload.path });
    return;
  }
  const message =
    typeof payload.message === 'string' && payload.message.trim().length > 0
      ? payload.message
      : 'The workspace directory could not be used.';
  pending.resolve({ status: 'error', message });
}

window.basilBoardBridge = {
  ...window.basilBoardBridge,
  onWorkspaceDirectoryPicked: (payload) => handleWorkspaceDirectoryPicked(payload),
};

function bridgeAvailable(): boolean {
  return Boolean(window.webkit?.messageHandlers?.basilBoardBridge);
}

export function postBridgeMessage(type: string, payload: Record<string, unknown> = {}): void {
  const message = { type, ...payload };
  if (!bridgeAvailable()) {
    console.error('[BasilBoardBridge] basilBoardBridge handler unavailable; message dropped', message);
    return;
  }
  window.webkit!.messageHandlers!.basilBoardBridge!.postMessage(message);
}

export function notifyReady(): void {
  postBridgeMessage('basilBoardReady');
}

export function requestWindowClose(): void {
  postBridgeMessage('requestWindowClose');
}

export function requestWindowMinimize(): void {
  postBridgeMessage('requestWindowMinimize');
}

export function openExistingAgentTaskWidget(agentTaskId: string): void {
  postBridgeMessage('openExistingAgentTaskWidget', { agentTaskId });
}

export function openConversationThreadWindow(conversationId: string, messageId?: string): void {
  postBridgeMessage(
    'openConversationThreadWindow',
    messageId ? { conversationId, messageId } : { conversationId },
  );
}

export function openExternalUrl(url: string): void {
  postBridgeMessage('openExternalUrl', { url });
}

export function copyToClipboard(text: string): void {
  postBridgeMessage('copyToClipboard', { text });
}

export function copyRichTextToClipboard(text: string): void {
  postBridgeMessage('copyRichTextToClipboard', { text });
}

export function startHomeVoiceCapture(): void {
  postBridgeMessage('startHomeVoiceCapture');
}

export function stopHomeVoiceCapture(): void {
  postBridgeMessage('stopHomeVoiceCapture');
}

export function cancelHomeVoiceCapture(): void {
  postBridgeMessage('cancelHomeVoiceCapture');
}

export function startConversationVoiceCapture(): void {
  postBridgeMessage('startConversationVoiceCapture');
}

export function stopConversationVoiceCapture(): void {
  postBridgeMessage('stopConversationVoiceCapture');
}

export function cancelConversationVoiceCapture(): void {
  postBridgeMessage('cancelConversationVoiceCapture');
}

export function setBoardFileDropTarget(target?: 'home' | 'conversation' | 'todoWorkspace'): void {
  postBridgeMessage('setBoardFileDropTarget', { target });
}

export function saveConversationPastedImages(dataUrls: string[]): void {
  postBridgeMessage('saveConversationPastedImages', { dataUrls });
}

export function pickHomeFiles(): void {
  postBridgeMessage('pickHomeFiles');
}

export function pickConversationFiles(): void {
  postBridgeMessage('pickConversationFiles');
}

export function pickTodoWorkspaceFiles(): void {
  postBridgeMessage('pickTodoWorkspaceFiles');
}

export function pickTodoReferenceFiles(): void {
  postBridgeMessage('pickTodoReferenceFiles');
}

export function pickWorkspaceDirectory(): Promise<WorkspaceDirectoryPickResult> {
  if (!bridgeAvailable()) {
    return Promise.resolve({ status: 'error', message: 'Native bridge is unavailable.' });
  }

  const requestId = `workspace-directory-${Date.now()}-${++workspaceDirectoryPickRequestCounter}`;

  return new Promise((resolve) => {
    const timeoutId = setTimeout(() => {
      pendingWorkspaceDirectoryPickRequests.delete(requestId);
      resolve({ status: 'error', message: 'Workspace directory picker timed out.' });
    }, 120000);

    pendingWorkspaceDirectoryPickRequests.set(requestId, { resolve, timeoutId });
    postBridgeMessage('pickWorkspaceDirectory', { requestId });
  });
}

export function detachBasilBoardTab(tabId: string): void {
  postBridgeMessage('detachBasilBoardTab', { tabId });
}

export function bringBasilBoardTabToFront(tabId: string): void {
  postBridgeMessage('bringBasilBoardTabToFront', { tabId });
}

export function openMeetingWorkspace(meetingId: string): void {
  postBridgeMessage('openMeetingWorkspace', { meetingId });
}

export function activateBoardAgentTasksSurface(): void {
  postBridgeMessage('activateBoardAgentTasksSurface');
}

export function deactivateBoardAgentTasksSurface(): void {
  postBridgeMessage('deactivateBoardAgentTasksSurface');
}

export function activateBoardMeetingsSurface(): void {
  postBridgeMessage('activateBoardMeetingsSurface');
}

export function deactivateBoardMeetingsSurface(): void {
  postBridgeMessage('deactivateBoardMeetingsSurface');
}

export function activateBoardConversationSurface(): void {
  postBridgeMessage('activateBoardConversationSurface');
}

export function deactivateBoardConversationSurface(): void {
  postBridgeMessage('deactivateBoardConversationSurface');
}

export function reportBoardChromeGeometry(payload: { contentLeft: number; contentTop: number }): void {
  postBridgeMessage('reportBoardChromeGeometry', payload);
}

export function requestWindowCollapse(): void {
  postBridgeMessage('requestWindowCollapse');
}

export function requestWindowExpand(): void {
  postBridgeMessage('requestWindowExpand');
}

export function openNativeBasilBoardTabWindow(tabId: string): void {
  postBridgeMessage('openNativeBasilBoardTabWindow', { tabId });
}

export function registerHomeFilesPickedHandler(handler: (paths: string[]) => void): () => void {
  filesPickedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onFilesPicked: (payload) => enqueueHomeFilesPicked(payload),
  };

  for (const paths of pendingFilesPicked) {
    handler(paths);
  }
  pendingFilesPicked.length = 0;

  return () => {
    if (filesPickedHandler === handler) {
      filesPickedHandler = null;
    }
  };
}

export function enqueueHomeFilesPicked(payload: { paths: string[] }): void {
  if (!Array.isArray(payload.paths)) {
    return;
  }
  const paths = payload.paths.filter((path): path is string => typeof path === 'string' && path.trim().length > 0);
  if (paths.length === 0) {
    return;
  }
  if (filesPickedHandler) {
    filesPickedHandler(paths);
    return;
  }
  pendingFilesPicked.push(paths);
}

export function registerConversationFilesPickedHandler(handler: (paths: string[]) => void): () => void {
  conversationFilesPickedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onConversationFilesPicked: (payload) => enqueueConversationFilesPicked(payload),
  };

  for (const paths of pendingConversationFilesPicked) {
    handler(paths);
  }
  pendingConversationFilesPicked.length = 0;

  return () => {
    if (conversationFilesPickedHandler === handler) {
      conversationFilesPickedHandler = null;
    }
  };
}

export function enqueueConversationFilesPicked(payload: { paths: string[] }): void {
  if (!Array.isArray(payload.paths)) {
    return;
  }
  const paths = payload.paths.filter((path): path is string => typeof path === 'string' && path.trim().length > 0);
  if (paths.length === 0) {
    return;
  }
  if (conversationFilesPickedHandler) {
    conversationFilesPickedHandler(paths);
    return;
  }
  pendingConversationFilesPicked.push(paths);
}

export function enqueueConversationComposerFocus(): void {
  if (conversationComposerFocusHandler) {
    conversationComposerFocusHandler();
    return;
  }
  pendingConversationComposerFocus = true;
}

export function registerConversationComposerFocusHandler(handler: () => void): () => void {
  conversationComposerFocusHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onFocusConversationComposer: () => enqueueConversationComposerFocus(),
  };
  if (pendingConversationComposerFocus) {
    pendingConversationComposerFocus = false;
    handler();
  }

  return () => {
    if (conversationComposerFocusHandler === handler) {
      conversationComposerFocusHandler = null;
    }
  };
}

export function registerTodoWorkspaceFilesPickedHandler(handler: (paths: string[]) => void): () => void {
  todoWorkspaceFilesPickedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onTodoWorkspaceFilesPicked: (payload) => enqueueTodoWorkspaceFilesPicked(payload),
  };

  for (const paths of pendingTodoWorkspaceFilesPicked) {
    handler(paths);
  }
  pendingTodoWorkspaceFilesPicked.length = 0;

  return () => {
    if (todoWorkspaceFilesPickedHandler === handler) {
      todoWorkspaceFilesPickedHandler = null;
    }
  };
}

export function enqueueTodoWorkspaceFilesPicked(payload: { paths: string[] }): void {
  if (!Array.isArray(payload.paths)) {
    return;
  }
  const paths = payload.paths.filter((path): path is string => typeof path === 'string' && path.trim().length > 0);
  if (paths.length === 0) {
    return;
  }
  if (todoWorkspaceFilesPickedHandler) {
    todoWorkspaceFilesPickedHandler(paths);
    return;
  }
  pendingTodoWorkspaceFilesPicked.push(paths);
}

export function registerTodoReferenceFilesPickedHandler(handler: (paths: string[]) => void): () => void {
  todoReferenceFilesPickedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onTodoReferenceFilesPicked: (payload) => enqueueTodoReferenceFilesPicked(payload),
  };

  for (const paths of pendingTodoReferenceFilesPicked) {
    handler(paths);
  }
  pendingTodoReferenceFilesPicked.length = 0;

  return () => {
    if (todoReferenceFilesPickedHandler === handler) {
      todoReferenceFilesPickedHandler = null;
    }
  };
}

export function enqueueTodoReferenceFilesPicked(payload: { paths: string[] }): void {
  if (!Array.isArray(payload.paths)) {
    return;
  }
  const paths = payload.paths.filter((path): path is string => typeof path === 'string' && path.trim().length > 0);
  if (paths.length === 0) {
    return;
  }
  if (todoReferenceFilesPickedHandler) {
    todoReferenceFilesPickedHandler(paths);
    return;
  }
  pendingTodoReferenceFilesPicked.push(paths);
}

export function registerConversationVoiceCaptureStateHandler(
  handler: (payload: ConversationVoiceCaptureStatePayload) => void,
): () => void {
  conversationVoiceStateHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onConversationVoiceCaptureState: (payload) => enqueueConversationVoiceCaptureState(payload),
  };

  for (const payload of pendingConversationVoiceStates) {
    handler(payload);
  }
  pendingConversationVoiceStates.length = 0;

  return () => {
    if (conversationVoiceStateHandler === handler) {
      conversationVoiceStateHandler = null;
    }
  };
}

export function enqueueConversationVoiceCaptureState(payload: ConversationVoiceCaptureStatePayload): void {
  if (conversationVoiceStateHandler) {
    conversationVoiceStateHandler(payload);
    return;
  }
  pendingConversationVoiceStates.push(payload);
}

export function registerConversationVoiceCaptureFinishedHandler(
  handler: (payload: ConversationVoiceCaptureFinishedPayload) => void,
): () => void {
  conversationVoiceFinishedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onConversationVoiceCaptureFinished: (payload) => enqueueConversationVoiceCaptureFinished(payload),
  };

  for (const payload of pendingConversationVoiceFinished) {
    handler(payload);
  }
  pendingConversationVoiceFinished.length = 0;

  return () => {
    if (conversationVoiceFinishedHandler === handler) {
      conversationVoiceFinishedHandler = null;
    }
  };
}

export function enqueueConversationVoiceCaptureFinished(payload: ConversationVoiceCaptureFinishedPayload): void {
  if (conversationVoiceFinishedHandler) {
    conversationVoiceFinishedHandler(payload);
    return;
  }
  pendingConversationVoiceFinished.push(payload);
}

export function registerConversationAttachmentErrorHandler(
  handler: (message: string) => void,
): () => void {
  conversationAttachmentErrorHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onConversationAttachmentError: (payload) => enqueueConversationAttachmentError(payload),
  };

  for (const message of pendingConversationAttachmentErrors) {
    handler(message);
  }
  pendingConversationAttachmentErrors.length = 0;

  return () => {
    if (conversationAttachmentErrorHandler === handler) {
      conversationAttachmentErrorHandler = null;
    }
  };
}

export function enqueueConversationAttachmentError(payload: { message: string }): void {
  const message = typeof payload?.message === 'string' ? payload.message.trim() : '';
  if (!message) return;
  if (conversationAttachmentErrorHandler) {
    conversationAttachmentErrorHandler(message);
    return;
  }
  pendingConversationAttachmentErrors.push(message);
}

export function registerDetachedTabsChangedHandler(handler: DetachedTabsChangedHandler): () => void {
  detachedTabsChangedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onDetachedBoardTabsChanged: (payload) => enqueueDetachedTabsChanged(payload),
  };

  for (const payload of pendingDetachedTabsChanged) {
    handler(payload);
  }
  pendingDetachedTabsChanged.length = 0;

  return () => {
    if (detachedTabsChangedHandler === handler) {
      detachedTabsChangedHandler = null;
    }
  };
}

export function enqueueDetachedTabsChanged(payload: DetachedTabsChangedPayload): void {
  if (!Array.isArray(payload.detachedTabIds)) {
    return;
  }
  if (detachedTabsChangedHandler) {
    detachedTabsChangedHandler(payload);
    return;
  }
  pendingDetachedTabsChanged.push(payload);
}

export function registerDetachedConversationsChangedHandler(
  handler: DetachedConversationsChangedHandler,
): () => void {
  detachedConversationsChangedHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onDetachedConversationsChanged: (payload) => enqueueDetachedConversationsChanged(payload),
  };

  for (const payload of pendingDetachedConversationsChanged) {
    handler(payload);
  }
  pendingDetachedConversationsChanged.length = 0;

  return () => {
    if (detachedConversationsChangedHandler === handler) {
      detachedConversationsChangedHandler = null;
    }
  };
}

export function enqueueDetachedConversationsChanged(payload: DetachedConversationsChangedPayload): void {
  if (!Array.isArray(payload.conversationIds)) {
    return;
  }
  if (detachedConversationsChangedHandler) {
    detachedConversationsChangedHandler(payload);
    return;
  }
  pendingDetachedConversationsChanged.push(payload);
}

export function registerAgentTaskOriginNavigationHandler(
  handler: AgentTaskOriginNavigationHandler,
): () => void {
  agentTaskOriginNavigationHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onNavigateToAgentTaskOrigin: enqueueAgentTaskOriginNavigation,
  };
  if (pendingAgentTaskOriginNavigation) {
    handler(pendingAgentTaskOriginNavigation);
    pendingAgentTaskOriginNavigation = null;
  }
  return () => {
    if (agentTaskOriginNavigationHandler === handler) {
      agentTaskOriginNavigationHandler = null;
    }
  };
}

export function enqueueAgentTaskOriginNavigation(payload: AgentTaskOriginNavigationPayload): void {
  const allowedOrigins = new Set(['todo', 'todo_workspace', 'scheduled_task', 'meeting', 'conversation']);
  if (
    !payload
    || !allowedOrigins.has(payload.originType)
    || typeof payload.originId !== 'string'
    || !payload.originId.trim()
  ) {
    return;
  }
  if (agentTaskOriginNavigationHandler) {
    agentTaskOriginNavigationHandler(payload);
  } else {
    pendingAgentTaskOriginNavigation = payload;
  }
}

export function registerBoardAgentTasksAvailabilityHandler(
  handler: BoardAgentTasksAvailabilityHandler,
): () => void {
  boardAgentTasksAvailabilityHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onBoardAgentTasksAvailabilityChanged: (payload) => enqueueBoardAgentTasksAvailabilityChanged(payload),
  };

  for (const payload of pendingBoardAgentTasksAvailability) {
    handler(payload);
  }
  pendingBoardAgentTasksAvailability.length = 0;

  return () => {
    if (boardAgentTasksAvailabilityHandler === handler) {
      boardAgentTasksAvailabilityHandler = null;
    }
  };
}

export function enqueueBoardAgentTasksAvailabilityChanged(payload: BoardAgentTasksAvailabilityPayload): void {
  if (payload.availability !== 'embedded' && payload.availability !== 'separate_window') {
    return;
  }
  if (boardAgentTasksAvailabilityHandler) {
    boardAgentTasksAvailabilityHandler(payload);
    return;
  }
  pendingBoardAgentTasksAvailability.push(payload);
}

export function registerBoardMeetingsAvailabilityHandler(
  handler: BoardMeetingsAvailabilityHandler,
): () => void {
  boardMeetingsAvailabilityHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onBoardMeetingsAvailabilityChanged: (payload) => enqueueBoardMeetingsAvailabilityChanged(payload),
  };

  for (const payload of pendingBoardMeetingsAvailability) {
    handler(payload);
  }
  pendingBoardMeetingsAvailability.length = 0;

  return () => {
    if (boardMeetingsAvailabilityHandler === handler) {
      boardMeetingsAvailabilityHandler = null;
    }
  };
}

export function enqueueBoardMeetingsAvailabilityChanged(payload: BoardMeetingsAvailabilityPayload): void {
  if (payload.availability !== 'embedded' && payload.availability !== 'separate_window') {
    return;
  }
  if (boardMeetingsAvailabilityHandler) {
    boardMeetingsAvailabilityHandler(payload);
    return;
  }
  pendingBoardMeetingsAvailability.push(payload);
}

export function registerBoardConversationAvailabilityHandler(
  handler: BoardConversationAvailabilityHandler,
): () => void {
  boardConversationAvailabilityHandler = handler;
  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onBoardConversationAvailabilityChanged: (payload) => enqueueBoardConversationAvailabilityChanged(payload),
  };

  for (const payload of pendingBoardConversationAvailability) {
    handler(payload);
  }
  pendingBoardConversationAvailability.length = 0;

  return () => {
    if (boardConversationAvailabilityHandler === handler) {
      boardConversationAvailabilityHandler = null;
    }
  };
}

export function enqueueBoardConversationAvailabilityChanged(payload: BoardConversationAvailabilityPayload): void {
  if (payload.availability !== 'available' && payload.availability !== 'unavailable') {
    return;
  }
  if (boardConversationAvailabilityHandler) {
    boardConversationAvailabilityHandler(payload);
    return;
  }
  pendingBoardConversationAvailability.push(payload);
}

export function registerBridgeHandlers(handlers: {
  onInit: InitHandler;
  onVoiceCaptureState: VoiceStateHandler;
  onVoiceCaptureFinished: VoiceFinishedHandler;
  onStatusIconChanged: StatusIconHandler;
}): void {
  const handleInit = (payload: BasilBoardInitPayload) => {
    handlers.onInit(payload);
    window.requestAnimationFrame(() => postBridgeMessage('basilBoardThemeApplied'));
  };

  initHandler = handleInit;
  voiceStateHandler = handlers.onVoiceCaptureState;
  voiceFinishedHandler = handlers.onVoiceCaptureFinished;
  statusIconHandler = handlers.onStatusIconChanged;

  window.basilBoardBridge = {
    ...window.basilBoardBridge,
    onInit: (payload) => handleInit(payload),
    // Theme changes must not replay init: init also carries the window's conversation identity and presentation, which an empty replay would reset.
    onThemeChanged: (payload) => {
      applyHostTheme(payload.theme);
      applyHostFonts(payload.fonts);
      window.requestAnimationFrame(() => postBridgeMessage('basilBoardThemeApplied'));
    },
    onVoiceCaptureState: (payload) => handlers.onVoiceCaptureState(payload),
    onVoiceCaptureFinished: (payload) => handlers.onVoiceCaptureFinished(payload),
    onConversationVoiceCaptureState: (payload) => enqueueConversationVoiceCaptureState(payload),
    onConversationVoiceCaptureFinished: (payload) => enqueueConversationVoiceCaptureFinished(payload),
    onConversationAttachmentError: (payload) => enqueueConversationAttachmentError(payload),
    onStatusIconChanged: (payload) => enqueueStatusIconChanged(payload),
    onFilesPicked: (payload) => enqueueHomeFilesPicked(payload),
    onConversationFilesPicked: (payload) => enqueueConversationFilesPicked(payload),
    onFocusConversationComposer: () => enqueueConversationComposerFocus(),
    onTodoWorkspaceFilesPicked: (payload) => enqueueTodoWorkspaceFilesPicked(payload),
    onTodoReferenceFilesPicked: (payload) => enqueueTodoReferenceFilesPicked(payload),
    onDetachedBoardTabsChanged: (payload) => enqueueDetachedTabsChanged(payload),
    onDetachedConversationsChanged: (payload) => enqueueDetachedConversationsChanged(payload),
    onBoardAgentTasksAvailabilityChanged: (payload) => enqueueBoardAgentTasksAvailabilityChanged(payload),
    onBoardConversationAvailabilityChanged: (payload) => enqueueBoardConversationAvailabilityChanged(payload),
    onBoardMeetingsAvailabilityChanged: (payload) => enqueueBoardMeetingsAvailabilityChanged(payload),
  };

  for (const payload of pendingInit) handlers.onInit(payload);
  pendingInit.length = 0;
  for (const payload of pendingVoiceStates) handlers.onVoiceCaptureState(payload);
  pendingVoiceStates.length = 0;
  for (const payload of pendingVoiceFinished) handlers.onVoiceCaptureFinished(payload);
  pendingVoiceFinished.length = 0;
  for (const payload of pendingStatusIcons) handlers.onStatusIconChanged(payload);
  pendingStatusIcons.length = 0;
}

export function enqueueInit(payload: BasilBoardInitPayload): void {
  if (initHandler) {
    initHandler(payload);
    return;
  }
  pendingInit.push(payload);
}

export function enqueueVoiceCaptureState(payload: HomeVoiceCaptureStatePayload): void {
  if (voiceStateHandler) {
    voiceStateHandler(payload);
    return;
  }
  pendingVoiceStates.push(payload);
}

export function enqueueVoiceCaptureFinished(payload: HomeVoiceCaptureFinishedPayload): void {
  if (voiceFinishedHandler) {
    voiceFinishedHandler(payload);
    return;
  }
  pendingVoiceFinished.push(payload);
}

export function enqueueStatusIconChanged(payload: { dataUrl: string }): void {
  if (typeof payload?.dataUrl !== 'string' || !payload.dataUrl.startsWith('data:image/png;base64,')) {
    return;
  }
  if (statusIconHandler) {
    statusIconHandler(payload);
    return;
  }
  pendingStatusIcons.push(payload);
}
