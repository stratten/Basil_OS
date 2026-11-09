import type { AgentState, TimelineEntry } from '../../types';
import { isAnsweredPrompt } from '../../store/agentStore/answeredPrompts';
import { userInteractionsFromTimeline, type UserInteraction } from './userInteractions';

/** The kinds of waiting request that are answered through the question card (the checkpoint overlay), as opposed to the approval, command-input, and connection overlays that have their own surfaces. */
const QUESTION_KINDS: ReadonlySet<string> = new Set(['clarification', 'provider_target', 'provider_input']);

/** The newest question the timeline records as still waiting for the user, or undefined when there is none. */
export function waitingQuestionInteraction(timeline: TimelineEntry[] | undefined): UserInteraction | undefined {
  const waiting = userInteractionsFromTimeline(timeline)
    .filter(interaction => interaction.status === 'waiting' && QUESTION_KINDS.has(interaction.kind));
  return waiting[waiting.length - 1];
}

type QuestionRecoveryInput = Pick<AgentState, 'status' | 'executionTimeline'> & Partial<Pick<
  AgentState,
  | 'currentCheckpoint'
  | 'inlineCheckpoint'
  | 'showCheckpointPrompt'
  | 'showApprovalPrompt'
  | 'showTokenConnectPrompt'
  | 'isCheckpointResumePending'
  | 'answeredPrompts'
>>;

/**
 * True when the run is waiting for an answer, by its status or by the timeline, but the window holds nothing to answer it with: no question card and no skipped-question card. The card for this state offers to load the question from the backend, so a waiting run is never left looking stuck.
 *
 * A question the user has just answered is excluded even while the timeline still shows it waiting, because the answer is remembered the moment it is sent and the timeline catches up a moment later.
 */
export function questionNeedsRecovery(agent: QuestionRecoveryInput | null | undefined): UserInteraction | 'status' | undefined {
  if (!agent) return undefined;
  if (agent.status === 'completed' || agent.status === 'failed') return undefined;
  if (agent.currentCheckpoint || agent.inlineCheckpoint || agent.showCheckpointPrompt) return undefined;
  if (agent.showApprovalPrompt || agent.showTokenConnectPrompt) return undefined;
  if (agent.isCheckpointResumePending) return undefined;

  const waiting = waitingQuestionInteraction(agent.executionTimeline);
  if (waiting) {
    return isAnsweredPrompt(agent.answeredPrompts, waiting.id) ? undefined : waiting;
  }
  return agent.status === 'awaitingInput' ? 'status' : undefined;
}
