import type { AssistantSessionStatus } from '../bridge/types';

/** Port of `assistantSessionProgressMessage` in AssistantSessionWidget_SharedComponents.swift. */
export function assistantSessionProgressMessage(
  ocrStatus: AssistantSessionStatus,
  transcriptionStatus: AssistantSessionStatus,
  assistantSessionStatus: AssistantSessionStatus,
  transcriptionProgressMessage: string | null,
): string | null {
  if (ocrStatus === 'running') return 'Running OCR...';
  if (ocrStatus === 'failed') return 'OCR failed';

  if (ocrStatus === 'completed') {
    if (transcriptionStatus === 'idle') return 'Ready to record';
    if (transcriptionStatus === 'running') {
      if (transcriptionProgressMessage && transcriptionProgressMessage.length > 0) {
        return transcriptionProgressMessage;
      }
      return 'Recording audio...';
    }
    if (transcriptionStatus === 'completed' && assistantSessionStatus === 'idle') {
      return 'Uploading audio...';
    }
  }

  if (assistantSessionStatus === 'running') return 'Processing full request...';
  if (assistantSessionStatus === 'completed') return 'Complete!';
  if (transcriptionStatus === 'failed' || assistantSessionStatus === 'failed') {
    return 'An error occurred.';
  }
  return null;
}
