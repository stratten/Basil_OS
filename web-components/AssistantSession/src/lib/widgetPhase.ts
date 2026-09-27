import type { AssistantSessionState } from '../state/assistantSessionReducer';

export type WidgetPhase = 'recording' | 'typedInput' | 'processing' | 'result';

/** Ports the load-bearing AssistantSessionWidget phase order exactly: nonempty result, visible failure, uncommitted input, then processing. */
export function deriveWidgetPhase(state: AssistantSessionState): WidgetPhase {
  if (state.assistantOutput.length > 0) {
    return 'result';
  }
  if (
    state.assistantSessionStatus === 'failed' ||
    state.ocrStatus === 'failed' ||
    state.transcriptionStatus === 'failed'
  ) {
    return 'processing';
  }
  if (state.assistantSessionStatus === 'running') {
    return 'processing';
  }
  if (!state.inputCommitted) {
    return state.inputMode === 'type' ? 'typedInput' : 'recording';
  }
  return 'processing';
}
