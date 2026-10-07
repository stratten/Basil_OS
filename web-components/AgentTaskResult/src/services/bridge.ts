import type {
  SwiftMessage,
  InitMessage,
  RegisterNewAgentMessage,
  FilePreviewInitMessage,
  CaptureStateMessage,
  ThemeConfig,
  FontConfig,
  ValidationRunFocusRequest,
  ValidationRunFocusState,
} from '../types';
import {
  createFilePreviewRequestManager,
  type ArtifactPreviewTransport,
  type FilePreviewKind,
  type FilePreviewPayload,
  type InlineNativePreviewFrame,
} from '../components/artifacts/transport/artifactPreviewTransport';
import { publishCaptureMeter } from '../store/captureMeterStore';
import { createSwiftBridge, missingHandlerLogger } from '@shared/swiftBridge';

export type { ArtifactPreviewTransport, FilePreviewKind, FilePreviewPayload, InlineNativePreviewFrame };

export interface FilePreviewAvailabilityPayload {
  requestId: string;
  availablePaths: string[];
}

declare global {
  interface Window {
    basilAgentTask?: {
      onInit: (config: InitMessage) => void;
      onCaptureStateChanged: (state: CaptureStateMessage) => void;
      onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => void;
      /**
       * Swift-driven push of the date display preference (relative/absolute).
       * Lets the result widget's history timestamps re-render live when the
       * user changes the setting in the General tab. Implemented by
       * ``registerDateStyleHandler``.
       */
      onDateStyleChanged: (style: string) => void;
      onDetachedRootsChanged: (rootTaskIds: string[]) => void;
      onFilesPicked: (paths: string[]) => void;
      requestFollowUpCapture: () => void;
      onExpandChromeForTaskCompletion: () => void;
      /**
       * Swift-driven entry point for "a new agentTask run has just been
       * kicked off; register and focus it." When ``rootTaskId``
       * is present, the run is a follow-up of an existing task and
       * MUST be folded into that parent's history rather than spawning
       * its own sidebar row — failure to honor it visually hides the
       * parent card until the widget is reopened (the "follow-up hides
       * the initial AgentTask" regression). The field is optional so
       * non-follow-up call sites (initial new-AgentTask captures, the
       * deep-link `show()` initial-AgentTask branch) can keep emitting
       * the same shape they always did.
       */
      onRegisterNewAgent: (data: RegisterNewAgentMessage) => void;
      /**
       * External entry point used by Swift when the user clicks a row in the
       * floating ScheduledRunMiniPanel. The result widget jumps to the
       * specified existing AgentTask in the agent store (selecting it like a
       * normal sidebar click). Implemented by ``registerShowExistingAgentTaskHandler``.
       */
      showExistingAgentTask: (agentTaskId: string) => void;
      showScheduledAgentTask: (scheduledAgentTaskId: string) => void;
      onRequestValidationRunState: (requestId: string) => void;
      onFocusValidationRun: (request: Required<ValidationRunFocusRequest>) => void;
      onRestoreValidationManagedHistory: (requestId: string) => void;
      /**
       * Swift-driven entry point for "the provisional agent_task_id we
       * pre-registered at capture-handoff will never become a backend
       * record." Posted by ``AgentTaskResultWidgetController`` after
       * ``AgentTaskCaptureViewModel`` parses an unsuccessful
       * ``/process-audio`` response (no speech detected, transcription
       * failed, network error, etc.). The React handler removes the
       * transient row if it has no durable data yet, otherwise marks it
       * as failed with the supplied message. Without this the row would
       * stay in "Processing..." and ``App.tsx``'s polling loop would
       * keep hitting 404 on the never-persisted ID.
       */
      onProvisionalTaskFailed: (payload: ProvisionalTaskFailedPayload) => void;
      onFilePreviewInit: (config: FilePreviewInitMessage) => void;
      onFilePreviewReady: (payload: FilePreviewPayload) => void;
      onFilePreviewUpdated: (payload: FilePreviewPayload) => void;
      onFilePreviewAvailability: (payload: FilePreviewAvailabilityPayload) => void;
    };
  }
}

export interface ProvisionalTaskFailedPayload {
  agentTaskId: string;
  reason: string;
  message: string;
  rootTaskId?: string;
  previousTaskId?: string;
}

let initCallback: ((config: InitMessage) => void) | null = null;
let filePreviewInitCallback: ((config: FilePreviewInitMessage) => void) | null = null;
let captureCallback: ((state: CaptureStateMessage) => void) | null = null;
let lastNonMeterCaptureState: Omit<CaptureStateMessage, 'audioLevel'> | null = null;
let themeCallback: ((theme: ThemeConfig, fonts: FontConfig) => void) | null = null;
let dateStyleCallback: ((style: string) => void) | null = null;
let detachedRootsCallback: ((rootTaskIds: string[]) => void) | null = null;
let filesPickedCallback: ((paths: string[]) => void) | null = null;
let requestFollowUpCallback: (() => void) | null = null;
let expandChromeForTaskCompletionCallback: (() => void) | null = null;
let registerNewAgentCallback: ((data: RegisterNewAgentMessage) => void) | null = null;
let showExistingAgentTaskCallback: ((agentTaskId: string) => void) | null = null;
let showScheduledAgentTaskCallback: ((scheduledAgentTaskId: string) => void) | null = null;
let validationRunStateRequestCallback: ((requestId: string) => void) | null = null;
let validationRunFocusCallback: ((request: Required<ValidationRunFocusRequest>) => void) | null = null;
let validationManagedHistoryRestoreCallback: ((requestId: string) => void) | null = null;
let provisionalTaskFailedCallback: ((payload: ProvisionalTaskFailedPayload) => void) | null = null;
let filePreviewAvailabilityRequestCounter = 0;
const pendingFilePreviewAvailabilityRequests = new Map<
  string,
  {
    resolve: (availablePaths: Set<string>) => void;
    reject: (error: Error) => void;
    timeoutId: ReturnType<typeof setTimeout>;
  }
>();
let filePreviewReadyCallback: ((payload: FilePreviewPayload) => void) | null = null;
let filePreviewUpdatedCallback: ((payload: FilePreviewPayload) => void) | null = null;

export const agentTaskArtifactPreviewTransport: ArtifactPreviewTransport = createFilePreviewRequestManager(
  (message) => postToSwift(message),
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
// Held until React mounts and registers a real handler. Without this,
// a Swift-driven jump that races the load would silently no-op.
let pendingShowExistingAgentTask: string | null = null;
let pendingShowScheduledAgentTask: string | null = null;
let pendingValidationRunStateRequest: string | null = null;
const pendingValidationRunFocusRequests: Required<ValidationRunFocusRequest>[] = [];
let pendingValidationManagedHistoryRestore: string | null = null;
const pendingRegisterNewAgent: RegisterNewAgentMessage[] = [];
// Held until App.tsx mounts and calls registerProvisionalTaskFailedHandler.
// Provisional failures can fire before the React result widget has finished
// mounting (the capture VM and the result widget controller live in
// parallel), so without this queue an early failure would silently no-op
// and the row would stay stuck in "Processing..."
const pendingProvisionalTaskFailed: ProvisionalTaskFailedPayload[] = [];

let pendingInit: InitMessage | null = null;
let pendingFilePreviewInit: FilePreviewInitMessage | null = null;
let pendingDetachedRoots: string[] | null = null;
let embeddedFlagCallback: ((embedded: boolean) => void) | null = null;
let pendingEmbeddedFlag: boolean | null = null;
let pendingExpandChromeForTaskCompletion = false;

export function registerEmbeddedFlagHandler(cb: (embedded: boolean) => void) {
  embeddedFlagCallback = cb;
  if (pendingEmbeddedFlag !== null) {
    cb(pendingEmbeddedFlag);
    pendingEmbeddedFlag = null;
  }
}

export function registerInitHandler(cb: (config: InitMessage) => void) {
  initCallback = cb;
  if (pendingInit) {
    cb(pendingInit);
    pendingInit = null;
  }
}

export function registerFilePreviewInitHandler(cb: (config: FilePreviewInitMessage) => void) {
  filePreviewInitCallback = cb;
  if (pendingFilePreviewInit) {
    cb(pendingFilePreviewInit);
    pendingFilePreviewInit = null;
  }
}

export function registerFilePreviewUpdateHandler(cb: (payload: FilePreviewPayload) => void) {
  return agentTaskArtifactPreviewTransport.registerFilePreviewUpdateHandler(cb);
}

export function registerCaptureHandler(cb: (state: CaptureStateMessage) => void) {
  captureCallback = cb;
  lastNonMeterCaptureState = null;
}

function captureStateNonMeterFieldsChanged(state: CaptureStateMessage): boolean {
  if (!lastNonMeterCaptureState) return true;
  return (
    lastNonMeterCaptureState.type !== state.type
    || lastNonMeterCaptureState.isCapturing !== state.isCapturing
    || lastNonMeterCaptureState.wordsDetected !== state.wordsDetected
    || lastNonMeterCaptureState.silenceProgress !== state.silenceProgress
  );
}

export function __resetCaptureStateBridgeForTests() {
  captureCallback = null;
  lastNonMeterCaptureState = null;
}

export function registerThemeHandler(cb: (theme: ThemeConfig, fonts: FontConfig) => void) {
  themeCallback = cb;
}

export function registerDateStyleHandler(cb: (style: string) => void) {
  dateStyleCallback = cb;
}

export function registerDetachedRootsHandler(cb: (rootTaskIds: string[]) => void) {
  detachedRootsCallback = cb;
  if (pendingDetachedRoots) {
    cb(pendingDetachedRoots);
    pendingDetachedRoots = null;
  }
}

export function registerFilesPickedHandler(cb: (paths: string[]) => void) {
  filesPickedCallback = cb;
}

export function registerRequestFollowUpHandler(cb: () => void) {
  requestFollowUpCallback = cb;
}

export function registerExpandChromeForTaskCompletionHandler(cb: () => void) {
  expandChromeForTaskCompletionCallback = cb;
  if (pendingExpandChromeForTaskCompletion) {
    pendingExpandChromeForTaskCompletion = false;
    cb();
  }
}

export function registerNewAgentHandler(cb: (data: RegisterNewAgentMessage) => void) {
  registerNewAgentCallback = cb;
  while (pendingRegisterNewAgent.length > 0) {
    const pending = pendingRegisterNewAgent.shift();
    if (pending) cb(pending);
  }
}

export function registerShowExistingAgentTaskHandler(cb: (agentTaskId: string) => void) {
  showExistingAgentTaskCallback = cb;
  if (pendingShowExistingAgentTask) {
    cb(pendingShowExistingAgentTask);
    pendingShowExistingAgentTask = null;
  }
}

export function registerShowScheduledAgentTaskHandler(cb: (scheduledAgentTaskId: string) => void) {
  showScheduledAgentTaskCallback = cb;
  if (pendingShowScheduledAgentTask) {
    cb(pendingShowScheduledAgentTask);
    pendingShowScheduledAgentTask = null;
  }
}

export function registerValidationRunStateRequestHandler(cb: (requestId: string) => void) {
  validationRunStateRequestCallback = cb;
  if (pendingValidationRunStateRequest) {
    cb(pendingValidationRunStateRequest);
    pendingValidationRunStateRequest = null;
  }
  return () => {
    if (validationRunStateRequestCallback === cb) validationRunStateRequestCallback = null;
  };
}

export function registerValidationRunFocusHandler(cb: (request: Required<ValidationRunFocusRequest>) => void) {
  validationRunFocusCallback = cb;
  while (pendingValidationRunFocusRequests.length > 0) {
    const pending = pendingValidationRunFocusRequests.shift();
    if (pending) cb(pending);
  }
  return () => {
    if (validationRunFocusCallback === cb) validationRunFocusCallback = null;
  };
}

export function registerValidationManagedHistoryRestoreHandler(cb: (requestId: string) => void) {
  validationManagedHistoryRestoreCallback = cb;
  if (pendingValidationManagedHistoryRestore) {
    cb(pendingValidationManagedHistoryRestore);
    pendingValidationManagedHistoryRestore = null;
  }
  return () => {
    if (validationManagedHistoryRestoreCallback === cb) validationManagedHistoryRestoreCallback = null;
  };
}

export function registerProvisionalTaskFailedHandler(
  cb: (payload: ProvisionalTaskFailedPayload) => void
) {
  provisionalTaskFailedCallback = cb;
  while (pendingProvisionalTaskFailed.length > 0) {
    const pending = pendingProvisionalTaskFailed.shift();
    if (pending) cb(pending);
  }
}

window.basilAgentTask = {
  onInit: (config: InitMessage) => {
    const embedded = Boolean(config.embedded);
    if (embeddedFlagCallback) {
      embeddedFlagCallback(embedded);
    } else {
      pendingEmbeddedFlag = embedded;
    }
    if (initCallback) {
      initCallback(config);
    } else {
      pendingInit = config;
    }
  },
  onCaptureStateChanged: (state: CaptureStateMessage) => {
    publishCaptureMeter(state.audioLevel);
    if (!captureStateNonMeterFieldsChanged(state)) return;
    lastNonMeterCaptureState = {
      type: state.type,
      isCapturing: state.isCapturing,
      wordsDetected: state.wordsDetected,
      silenceProgress: state.silenceProgress,
    };
    captureCallback?.(state);
  },
  onThemeChanged: (theme: ThemeConfig, fonts: FontConfig) => themeCallback?.(theme, fonts),
  onDateStyleChanged: (style: string) => dateStyleCallback?.(style),
  onDetachedRootsChanged: (rootTaskIds: string[]) => {
    if (detachedRootsCallback) {
      detachedRootsCallback(rootTaskIds);
    } else {
      pendingDetachedRoots = rootTaskIds;
    }
  },
  onFilesPicked: (paths: string[]) => filesPickedCallback?.(paths),
  requestFollowUpCapture: () => requestFollowUpCallback?.(),
  onExpandChromeForTaskCompletion: () => {
    if (expandChromeForTaskCompletionCallback) {
      expandChromeForTaskCompletionCallback();
    } else {
      pendingExpandChromeForTaskCompletion = true;
    }
  },
  onRegisterNewAgent: (data: RegisterNewAgentMessage) => {
    if (registerNewAgentCallback) {
      registerNewAgentCallback(data);
    } else {
      pendingRegisterNewAgent.push(data);
    }
  },
  showExistingAgentTask: (agentTaskId: string) => {
    if (showExistingAgentTaskCallback) {
      showExistingAgentTaskCallback(agentTaskId);
    } else {
      pendingShowExistingAgentTask = agentTaskId;
    }
  },
  showScheduledAgentTask: (scheduledAgentTaskId: string) => {
    if (showScheduledAgentTaskCallback) {
      showScheduledAgentTaskCallback(scheduledAgentTaskId);
    } else {
      pendingShowScheduledAgentTask = scheduledAgentTaskId;
    }
  },
  onRequestValidationRunState: (requestId: string) => {
    if (!requestId) return;
    if (validationRunStateRequestCallback) {
      validationRunStateRequestCallback(requestId);
    } else {
      pendingValidationRunStateRequest = requestId;
    }
  },
  onFocusValidationRun: (request: Required<ValidationRunFocusRequest>) => {
    if (!request.requestId || !request.runId) return;
    if (validationRunFocusCallback) {
      validationRunFocusCallback(request);
    } else {
      pendingValidationRunFocusRequests.push(request);
    }
  },
  onRestoreValidationManagedHistory: (requestId: string) => {
    if (!requestId) return;
    if (validationManagedHistoryRestoreCallback) {
      validationManagedHistoryRestoreCallback(requestId);
    } else {
      pendingValidationManagedHistoryRestore = requestId;
    }
  },
  onProvisionalTaskFailed: (payload: ProvisionalTaskFailedPayload) => {
    if (provisionalTaskFailedCallback) {
      provisionalTaskFailedCallback(payload);
    } else {
      pendingProvisionalTaskFailed.push(payload);
    }
  },
  onFilePreviewInit: (config: FilePreviewInitMessage) => {
    if (filePreviewInitCallback) {
      filePreviewInitCallback(config);
    } else {
      pendingFilePreviewInit = config;
    }
  },
  onFilePreviewReady: (payload: FilePreviewPayload) => {
    filePreviewReadyCallback?.(payload);
  },
  onFilePreviewUpdated: (payload: FilePreviewPayload) => {
    filePreviewUpdatedCallback?.(payload);
  },
  onFilePreviewAvailability: (payload: FilePreviewAvailabilityPayload) => {
    const pending = pendingFilePreviewAvailabilityRequests.get(payload.requestId);
    if (!pending) return;

    clearTimeout(pending.timeoutId);
    pendingFilePreviewAvailabilityRequests.delete(payload.requestId);
    pending.resolve(new Set(payload.availablePaths));
  },
};

const swiftBridge = createSwiftBridge<SwiftMessage>('agentTaskBridge', {
  onMissing: missingHandlerLogger('log', '[Bridge] No Swift handler, message:'),
});

function postToSwift(message: SwiftMessage) {
  swiftBridge.post(message);
}

export function closeWidget() {
  postToSwift({ type: 'closeWidget' });
}

export function minimizeWidget() {
  postToSwift({ type: 'minimizeWidget' });
}

export function reportResultWidgetReady() {
  postToSwift({ type: 'resultWidgetReady' });
}

export function reportValidationRunFocused(state: ValidationRunFocusState) {
  postToSwift({
    type: 'validationRunFocused',
    ...state,
  });
}

export function cancelRunningAgentTask(agentTaskId: string) {
  postToSwift({ type: 'cancelRunningAgentTask', agentTaskId });
}

export function reportAgentTaskCancellationStage(agentTaskId: string, stage: string) {
  postToSwift({ type: 'reportAgentTaskCancellationStage', agentTaskId, stage });
}

export function requestResize(
  width: number,
  height: number,
  resizeIntent: 'content' | 'collapsed' | 'expanded' | 'layout' = 'content',
  minimumWidth?: number,
) {
  postToSwift({
    type: 'requestResize',
    width,
    height,
    resizeIntent,
    ...(minimumWidth === undefined ? {} : { minimumWidth }),
  });
}

export function startFollowUpCapture(rootTaskId: string, previousTaskId?: string) {
  postToSwift({ type: 'startFollowUpCapture', rootTaskId, previousTaskId });
}

export function stopFollowUpCapture() {
  postToSwift({ type: 'stopFollowUpCapture' });
}

export function cancelFollowUpCapture() {
  postToSwift({ type: 'cancelFollowUpCapture' });
}

export function startNewAgentTaskCapture(preGeneratedId: string) {
  postToSwift({ type: 'startNewAgentTaskCapture', preGeneratedId });
}

export function stopNewAgentTaskCapture() {
  postToSwift({ type: 'stopNewAgentTaskCapture' });
}

export function cancelNewAgentTaskCapture() {
  postToSwift({ type: 'cancelNewAgentTaskCapture' });
}

export function startRefinementRecording() {
  postToSwift({ type: 'startRefinementRecording' });
}

export function stopRefinementRecording() {
  postToSwift({ type: 'stopRefinementRecording' });
}

export function copyToClipboard(text: string) {
  postToSwift({ type: 'copyToClipboard', text });
}

export function copyRichTextToClipboard(text: string) {
  postToSwift({ type: 'copyRichTextToClipboard', text });
}

export function openFile(path: string) {
  postToSwift({ type: 'openFile', path });
}

export function openFilePreviewWindow(path: string, context?: { agentTaskId?: string; rootTaskId?: string }) {
  postToSwift({ type: 'openFilePreviewWindow', path, agentTaskId: context?.agentTaskId, rootTaskId: context?.rootTaskId });
}

export function openLocalWebPreview(params: {
  mode: 'static' | 'devServer';
  targetUrl: string;
  artifactId: string;
  agentTaskId: string;
  rootTaskId?: string;
  canonicalPath?: string;
  sessionId?: string;
  displayName?: string;
}) {
  postToSwift({ type: 'openLocalWebPreview', ...params });
}

function buildLocalPreviewTargetUrl(path: string): string {
  return path.startsWith('http')
    ? path
    : `file://${path.split('/').map(segment => encodeURIComponent(segment)).join('/')}`;
}

export function buildStaticLocalWebPreview(
  path: string,
  agentTaskId: string,
  artifactId: string,
  rootTaskId: string,
): Parameters<typeof openLocalWebPreview>[0] {
  return {
    mode: 'static',
    targetUrl: buildLocalPreviewTargetUrl(path),
    artifactId,
    agentTaskId,
    rootTaskId,
    canonicalPath: path,
    displayName: path.split('/').pop() ?? 'Preview',
  };
}

export function buildLocalServerPreview(
  path: string,
  agentTaskId: string,
  artifactId: string,
  rootTaskId: string,
): Parameters<typeof openLocalWebPreview>[0] {
  return {
    mode: 'devServer',
    targetUrl: buildLocalPreviewTargetUrl(path),
    artifactId,
    agentTaskId,
    rootTaskId,
    canonicalPath: path,
    displayName: path.split('/').pop() ?? 'Preview',
  };
}

/**
 * Builds a `basil-inline-preview://` URL for the root-scoped scheme handler
 * registered once on AgentTaskResultWebView's shared, long-lived webview
 * (see AgentTaskResultWebView.swift). Only used by the inline tray's live
 * HTML surface -- the detached preview window keeps using its own
 * per-artifact-directory-scoped `basil-preview-file://` handler.
 */
export function buildInlineStaticPreviewUrl(path: string): string {
  return `basil-inline-preview://local${path.split('/').map(segment => encodeURIComponent(segment)).join('/')}`;
}

export function openContainingFolder(path: string) {
  postToSwift({ type: 'openContainingFolder', path });
}

export function reportFilePreviewChromeHeight(height: number) {
  postToSwift({ type: 'filePreviewChromeHeight', height });
}

export function reportWidgetHeaderHeight(height: number) {
  postToSwift({ type: 'widgetHeaderHeight', height });
}

export function setInlineNativePreviewFrame(requestId: string, frame: InlineNativePreviewFrame) {
  agentTaskArtifactPreviewTransport.setInlineNativePreviewFrame(requestId, frame);
}

export function hideInlineNativePreview(requestId: string) {
  agentTaskArtifactPreviewTransport.hideInlineNativePreview(requestId);
}

export function clearInlineNativePreview(requestId: string) {
  agentTaskArtifactPreviewTransport.clearInlineNativePreview(requestId);
}

export function clearFilePreview(requestId: string) {
  agentTaskArtifactPreviewTransport.clearFilePreview(requestId);
}

export function previewFile(path: string): Promise<FilePreviewPayload> {
  return agentTaskArtifactPreviewTransport.previewFile(path);
}

export function checkFilePreviewAvailability(paths: string[]): Promise<Set<string>> {
  const uniquePaths = [...new Set(paths)];
  if (uniquePaths.length === 0) return Promise.resolve(new Set());
  if (!swiftBridge.isAvailable()) return Promise.resolve(new Set(uniquePaths));

  const requestId = `file-preview-availability-${Date.now()}-${++filePreviewAvailabilityRequestCounter}`;
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      pendingFilePreviewAvailabilityRequests.delete(requestId);
      reject(new Error('File preview availability request timed out.'));
    }, 5000);

    pendingFilePreviewAvailabilityRequests.set(requestId, { resolve, reject, timeoutId });
    postToSwift({ type: 'checkFilePreviewAvailability', requestId, paths: uniquePaths });
  });
}

export function openExternalUrl(url: string) {
  postToSwift({ type: 'openExternalUrl', url });
}

export function openDetachedAgentTask(rootTaskId: string) {
  postToSwift({ type: 'openDetachedAgentTask', rootTaskId });
}

export function openAgentTaskOrigin(originType: string, originId: string) {
  postToSwift({ type: 'openAgentTaskOrigin', originType, originId });
}

export function pickFiles() {
  postToSwift({ type: 'pickFiles' });
}

/**
 * Push the current sidebar focus state to Swift. Read by the agentTask
 * hotkey handler (gate logic in `HotkeyHandler_AgentTask.swift`) to decide
 * whether the next hotkey press should start a follow-up against the
 * focused row or spawn a fresh capture widget.
 *
 * @param isProcessing    True iff the focused row's agent is currently
 *                        processing (status === 'processing' || 'routing').
 * @param hasResult       True iff the focused row's agent has produced a
 *                        terminal result (completed or failed, or
 *                        `result` populated).
 * @param isTerminal      True iff the focused row's status is completed or
 *                        failed, excluding intermediate states with output.
 * @param agentTaskId       Identifier of the focused row, or null when
 *                        nothing is focused. Required for follow-ups.
 * @param supportsFollowUp True iff the focused row is in a state that
 *                        can accept a follow-up. Excludes processing
 *                        agents and scheduled-run detail views.
 */
export function reportAgentStatus(
  isProcessing: boolean,
  hasResult: boolean,
  isTerminal: boolean,
  agentTaskId: string | null = null,
  supportsFollowUp: boolean = false
) {
  postToSwift({
    type: 'agentStatusChanged',
    isProcessing,
    hasResult,
    isTerminal,
    agentTaskId,
    supportsFollowUp,
  });
}
