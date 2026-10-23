import { selectCompanionStream, selectProposalsAwaitingDecision, selectUnseenEntries } from './companionStreamSelectors';
import type { CompanionStoreState } from './companionStore';
import { useCompanionView } from './companionViewStore';

export interface CompanionAwareness {
  /** Items and answers that arrived after the reader last had the stream in view. */
  unseenCount: number;
  /** Proposals still waiting for the reader's approval. */
  decisionCount: number;
}

/** What the Companion has for the reader that they have not looked at yet, for the surfaces outside the pane (the collapsed rail, the Companion switch, the detached window title). It reads the same per-meeting view state the pane writes, so the pane and these badges always agree. */
export function useCompanionAwareness(meetingId: string | null, state: CompanionStoreState): CompanionAwareness {
  const ready = state.phase === 'ready';
  const { view } = useCompanionView(meetingId, ready ? state.baselineSeq : null);
  if (!ready) return { unseenCount: 0, decisionCount: 0 };
  const stream = selectCompanionStream(state.timeline);
  return {
    unseenCount: selectUnseenEntries(stream, view.lastSeenSeq ?? state.baselineSeq).length,
    decisionCount: selectProposalsAwaitingDecision(state.timeline.items).length,
  };
}

/** The short text for a badge ("3 new", "1 to decide"), or null when there is nothing to flag. Decisions come first because they block on the reader. */
export function awarenessBadgeText(awareness: CompanionAwareness): string | null {
  if (awareness.decisionCount > 0) return `${awareness.decisionCount} to decide`;
  if (awareness.unseenCount > 0) return `${awareness.unseenCount} new`;
  return null;
}
