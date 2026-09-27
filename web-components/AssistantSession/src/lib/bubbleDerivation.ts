import type { AssistantSessionBubbleMode, AssistantSessionStatus, AssistantSessionThemePayload } from '../bridge/types';

export function isAssistantSessionProcessing(
  ocrStatus: AssistantSessionStatus,
  transcriptionStatus: AssistantSessionStatus,
  assistantSessionStatus: AssistantSessionStatus,
): boolean {
  return ocrStatus === 'running' || transcriptionStatus === 'running' || assistantSessionStatus === 'running';
}

export function deriveBubbleMode(
  isRecording: boolean,
  ocrStatus: AssistantSessionStatus,
  transcriptionStatus: AssistantSessionStatus,
  assistantSessionStatus: AssistantSessionStatus,
): AssistantSessionBubbleMode {
  if (isRecording) {
    return 'audioResponsive';
  }
  if (isAssistantSessionProcessing(ocrStatus, transcriptionStatus, assistantSessionStatus)) {
    return 'processing';
  }
  return 'ambient';
}

export function deriveBubbleColors(
  isRecording: boolean,
  isProcessing: boolean,
  theme: AssistantSessionThemePayload,
): { base: string; accent: string } {
  if (isRecording) {
    return { base: theme.recordingBase, accent: theme.recordingAccent };
  }
  if (isProcessing) {
    return { base: theme.processingBase, accent: theme.processingAccent };
  }
  return { base: theme.readyBase, accent: theme.readyAccent };
}
