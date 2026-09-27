import type { MeetingBridgeEvent, MeetingUIStateDTO, TranscriptLineDTO, TranscriptPatchDTO, MeetingListItemDTO, AnalysisMetadataEntryDTO, MeetingAnalysisResultDTO, MeetingActionProposalDTO, MeetingThemePayloadDTO, MeetingFontPayloadDTO } from '../bridge/types';

export interface MeetingState {
  connected: boolean;
  revision: number;
  selectionGeneration: number;
  ui: MeetingUIStateDTO | null;
  transcript: TranscriptLineDTO[];
  history: MeetingListItemDTO[];
  analysisHistory: AnalysisMetadataEntryDTO[];
  analysisResult: MeetingAnalysisResultDTO | null;
  proposals: MeetingActionProposalDTO[];
  theme: MeetingThemePayloadDTO | null;
  fonts: MeetingFontPayloadDTO | null;
  lastValidationError: { code: string; message: string } | null;
}

export const initialMeetingState: MeetingState = {
  connected: false,
  revision: -1,
  selectionGeneration: -1,
  ui: null,
  transcript: [],
  history: [],
  analysisHistory: [],
  analysisResult: null,
  proposals: [],
  theme: null,
  fonts: null,
  lastValidationError: null,
};

/**
 * Pure reducer: applies one bridge event to the current state. Contains no
 * fetches and no timers. Guards:
 *  - `revision` must be strictly greater than the currently applied
 *    revision for a `sessionDelta`/`transcriptDelta`/`historyDelta`/
 *    `analysisHistoryDelta` event, else the event is dropped (out-of-order
 *    or duplicate delivery).
 *  - a `transcriptDelta`, `analysisResultDelta`, or `proposalsDelta` whose
 *    `selectionGeneration` is older than the currently applied one is
 *    dropped outright, which is what stops a background meeting's data
 *    from ever overwriting the currently viewed selection.
 */
export function applyMeetingBridgeEvent(state: MeetingState, event: MeetingBridgeEvent): MeetingState {
  if (event.protocolVersion !== 4) {
    return state;
  }
  if (event.type === 'snapshot') {
    const isLoadingAnalysisResult = event.ui?.isLoadingAnalysisResult === true;
    return {
      ...state,
      connected: true,
      revision: event.revision,
      selectionGeneration: event.selectionGeneration,
      ui: event.ui ?? state.ui,
      transcript: event.transcript ?? [],
      history: event.history ?? [],
      analysisHistory: event.analysisHistory ?? [],
      analysisResult: isLoadingAnalysisResult ? null : (event.analysisResult ?? state.analysisResult),
      proposals: isLoadingAnalysisResult ? [] : (event.proposals ?? []),
      theme: event.theme ?? state.theme,
      fonts: event.fonts ?? state.fonts,
      lastValidationError: null,
    };
  }

  if (event.type === 'themeChanged') {
    return { ...state, theme: event.theme ?? state.theme, fonts: event.fonts ?? state.fonts };
  }

  if (event.revision <= state.revision) {
    return state;
  }

  if (event.type === 'validationError') {
    return {
      ...state,
      revision: event.revision,
      lastValidationError: {
        code: event.validationErrorCode ?? 'unknown',
        message: event.validationErrorMessage ?? 'An unexpected error occurred.',
      },
    };
  }

  switch (event.type) {
    case 'sessionDelta':
      if (event.selectionGeneration < state.selectionGeneration) return state;
      const isLoadingAnalysisResult = event.ui?.isLoadingAnalysisResult === true;
      return {
        ...state,
        revision: event.revision,
        selectionGeneration: event.selectionGeneration,
        ui: event.ui ?? state.ui,
        analysisResult: isLoadingAnalysisResult ? null : state.analysisResult,
        proposals: isLoadingAnalysisResult ? [] : state.proposals,
        lastValidationError: null,
      };
    case 'transcriptDelta':
      if (event.selectionGeneration < state.selectionGeneration) return state;
      return {
        ...state,
        revision: event.revision,
        selectionGeneration: event.selectionGeneration,
        transcript: applyTranscriptPatch(state.transcript, event.transcriptPatch, event.transcript),
      };
    case 'historyDelta':
      return { ...state, revision: event.revision, history: event.history ?? state.history };
    case 'analysisHistoryDelta':
      if (event.selectionGeneration < state.selectionGeneration) return state;
      return {
        ...state,
        revision: event.revision,
        selectionGeneration: event.selectionGeneration,
        analysisHistory: event.analysisHistory ?? state.analysisHistory,
      };
    case 'analysisResultDelta':
      if (event.selectionGeneration < state.selectionGeneration) return state;
      return {
        ...state,
        revision: event.revision,
        selectionGeneration: event.selectionGeneration,
        analysisResult: event.analysisResult ?? state.analysisResult,
        // Proposal state belongs to one saved analysis. Never render the
        // previous analysis's handled/To-Do statuses against a new result while
        // its matching proposalsDelta is in flight.
        proposals: [],
      };
    case 'proposalsDelta':
      if (event.selectionGeneration < state.selectionGeneration) return state;
      return {
        ...state,
        revision: event.revision,
        selectionGeneration: event.selectionGeneration,
        proposals: event.proposals ?? state.proposals,
      };
    default:
      return state;
  }
}

/** Merges a keyed transcript update without recreating unrelated rows. */
export function mergeTranscript(previous: TranscriptLineDTO[], next: TranscriptLineDTO[]): TranscriptLineDTO[] {
  const previousById = new Map(previous.map((line) => [line.id, line]));
  return next.map((line) => {
    const existing = previousById.get(line.id);
    return existing
      && existing.text === line.text
      && existing.speakerId === line.speakerId
      && existing.isInterim === line.isInterim
      && existing.displayStart === line.displayStart
      && existing.timelineStartSeconds === line.timelineStartSeconds
      && existing.timelineEndSeconds === line.timelineEndSeconds
      && existing.source === line.source
      && existing.lineComplete === line.lineComplete
      ? existing
      : line;
  });
}

export function applyTranscriptPatch(
  previous: TranscriptLineDTO[],
  patch: TranscriptPatchDTO | undefined,
  fullTranscript: TranscriptLineDTO[] | undefined,
): TranscriptLineDTO[] {
  if (fullTranscript) return mergeTranscript(previous, fullTranscript);
  if (!patch || (patch.orderedIDs.length === 0 && patch.upserts.length === 0 && patch.removedIDs.length === 0)) return previous;

  const removedIDs = new Set(patch.removedIDs);
  const linesByID = new Map(previous.filter((line) => !removedIDs.has(line.id)).map((line) => [line.id, line]));
  for (const line of patch.upserts) {
    linesByID.set(line.id, line);
  }

  return patch.orderedIDs.flatMap((id) => {
    const line = linesByID.get(id);
    return line ? [line] : [];
  });
}
