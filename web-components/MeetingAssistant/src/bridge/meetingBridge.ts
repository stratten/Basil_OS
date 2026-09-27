import type { MeetingBridgeEvent, MeetingBridgeIntent, MeetingHistorySearchFiltersDTO, MeetingMeterPayload } from './types';
import { publishMeetingMeter } from './meetingMeterStore';

declare global {
  interface Window {
    webkit?: {
      messageHandlers: {
        meetingBridge?: {
          postMessage: (message: MeetingBridgeIntent) => void;
        };
      };
    };
    basilMeetingAssistant?: {
      onEvent: (event: MeetingBridgeEvent) => void;
      onMeter: (payload: MeetingMeterPayload) => void;
    };
  }
}

const PROTOCOL_VERSION = 4;

let eventCallback: ((event: MeetingBridgeEvent) => void) | null = null;
const pendingEvents: MeetingBridgeEvent[] = [];

function installGlobalHandlers() {
  window.basilMeetingAssistant = {
    onEvent: (event: MeetingBridgeEvent) => {
      if (eventCallback) {
        eventCallback(event);
      } else {
        pendingEvents.push(event);
      }
    },
    onMeter: (payload: MeetingMeterPayload) => {
      publishMeetingMeter(payload);
    },
  };
}

installGlobalHandlers();

export function registerEventHandler(cb: (event: MeetingBridgeEvent) => void) {
  eventCallback = cb;
  if (!window.basilMeetingAssistant) {
    installGlobalHandlers();
  }
  while (pendingEvents.length > 0) {
    const pending = pendingEvents.shift();
    if (pending) cb(pending);
  }
}

function postToSwift(intent: MeetingBridgeIntent) {
  if (window.webkit?.messageHandlers.meetingBridge) {
    window.webkit.messageHandlers.meetingBridge.postMessage(intent);
  } else {
    // eslint-disable-next-line no-console
    console.log('[MeetingBridge] No Swift handler, intent:', intent);
  }
}

export function reportReady() {
  postToSwift({ type: 'reactReady', protocolVersion: PROTOCOL_VERSION });
}

export function closeWindow() {
  postToSwift({ type: 'closeWindow' });
}

export function minimizeWindow() {
  postToSwift({ type: 'minimizeWindow' });
}

export function toggleWindowCollapse(collapsed: boolean) {
  postToSwift({ type: 'toggleWindowCollapse', collapsed });
}

/// Reports the rendered height of `.meeting-window-chrome` so the native
/// drag overlay's height constraint matches actual layout. Mirrors
/// `AgentTaskResultWebView`'s `reportWidgetHeaderHeight`: a single
/// `offsetHeight` number, no coordinate/region data, because the header's
/// button clusters sit in the same fixed-width bands on every render.
export function reportChromeHeight(height: number) {
  postToSwift({ type: 'chromeHeight', height });
}

export function toggleRecording() {
  postToSwift({ type: 'toggleRecording' });
}

export function startNewMeeting() {
  postToSwift({ type: 'startNewMeeting' });
}

export function resumeMeeting() {
  postToSwift({ type: 'resumeMeeting' });
}

export function selectMeeting(meetingId: string) {
  postToSwift({ type: 'selectMeeting', meetingId });
}

export function deleteMeeting(meetingId: string) {
  postToSwift({ type: 'deleteMeeting', meetingId });
}

export function setSidebarCollapsed(collapsed: boolean) {
  postToSwift({ type: 'setSidebarCollapsed', collapsed });
}

export function setMeetingSearch(text: string) {
  postToSwift({ type: 'setMeetingSearch', text });
}

export function setMeetingSearchFilters(filters: MeetingHistorySearchFiltersDTO) {
  postToSwift({ type: 'setMeetingSearchFilters', ...filters });
}

export function loadMoreMeetings() {
  postToSwift({ type: 'loadMoreMeetings' });
}

export function updateMetadata(fields: { name?: string; purpose?: string; participants?: string }) {
  postToSwift({ type: 'updateMetadata', ...fields });
}

export function setAudioSource(fields: {
  enableMicrophone?: boolean;
  captureMode?: 'none' | 'selectedProcess' | 'globalOutput';
  processId?: number;
}) {
  postToSwift({ type: 'setAudioSource', ...fields });
}

export function setPostProcessingModel(model: string) {
  postToSwift({ type: 'setPostProcessingModel', model });
}

export function startPostProcessing(operation: 'transcribe' | 'diarize') {
  postToSwift({ type: 'startPostProcessing', operation });
}

export function setAutomation(fields: {
  autoRetranscribeOnStop?: boolean;
  autoRetranscribeDuringRecording?: boolean;
  autoAnalyzeOnComplete?: boolean;
  autoAnalyzeModes?: string[];
  autoAnalyzeCustomInstructions?: string;
  autoAnalyzeTiming?: string;
}) {
  postToSwift({ type: 'setAutomation', ...fields });
}

export function setAnalysisConfiguration(fields: { modes?: string[]; customInstructions?: string; modelId?: string; isExpanded?: boolean }) {
  postToSwift({ type: 'setAnalysisConfiguration', ...fields });
}

export function startAnalysis() {
  postToSwift({ type: 'startAnalysis' });
}

export function viewAnalysis(filename: string) {
  postToSwift({ type: 'viewAnalysis', filename });
}

export function deleteAnalysis(filename: string) {
  postToSwift({ type: 'deleteAnalysis', filename });
}

export function retryAnalysisModes(filename: string, modes: string[]) {
  postToSwift({ type: 'retryAnalysisModes', filename, modes });
}

export function copyText(text: string, rich: boolean = false) {
  if (window.webkit?.messageHandlers.meetingBridge) {
    postToSwift({ type: 'copyText', text, rich });
    return;
  }

  if (navigator.clipboard?.writeText) {
    void navigator.clipboard.writeText(text).catch((error: unknown) => {
      // eslint-disable-next-line no-console
      console.warn('[MeetingBridge] Browser clipboard write failed:', error);
    });
    return;
  }

  // eslint-disable-next-line no-console
  console.warn('[MeetingBridge] Clipboard API is unavailable.');
}

export function exportAnalysis(filename: string, format: 'markdown' | 'text' = 'markdown', text?: string, filenameSuggestion?: string) {
  postToSwift({ type: 'exportAnalysis', filename, format, text, filenameSuggestion });
}

export function updateProposal(proposalId: string, fields: { draftPrompt?: string; isEditingDraft?: boolean }) {
  postToSwift({ type: 'updateProposal', proposalId, ...fields });
}

export function promoteProposalToTodo(proposalId: string) {
  postToSwift({ type: 'promoteProposalToTodo', proposalId });
}

export function startProposalNow(proposalId: string) {
  postToSwift({ type: 'startProposalNow', proposalId });
}

export function openProposalTodo(todoId: string) {
  postToSwift({ type: 'openProposalTodo', todoId });
}

export function openProposalAgentTask(agentTaskId: string) {
  postToSwift({ type: 'openProposalAgentTask', agentTaskId });
}

export function promoteAllProposalsToTodos() {
  postToSwift({ type: 'promoteAllProposalsToTodos' });
}

export function dismissProposal(proposalId: string) {
  postToSwift({ type: 'dismissProposal', proposalId });
}

export function restoreProposal(proposalId: string) {
  postToSwift({ type: 'restoreProposal', proposalId });
}
