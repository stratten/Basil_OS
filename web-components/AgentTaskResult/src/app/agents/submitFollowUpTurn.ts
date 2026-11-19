import * as api from '../../services/api';
import { agentStore } from '../../store/agentStore';
import type { DisplayableAgentTask } from '../../types';
import { buildFollowUpHistoryFromViewedDetail } from './followUpHistory';
import { seedDurableFollowUpHistory } from './agentHydration';

export interface FollowUpTurnRequest {
  /** What the turn asks of Basil. */
  content: string;
  /** The same request as it should read in the conversation, when it differs from the plain text. */
  displayPromptMarkdown?: string;
  referencePaths: string[];
  /** The conversation the turn joins. */
  rootId: string;
  /** The task the follow-up box was opened on, used when the conversation has no entry in the store yet. */
  agentTaskId: string;
  /** The task as it is on screen. Reopened from history there is no store entry, so the whole conversation on screen is carried over from this. */
  displaySource?: DisplayableAgentTask;
  /** The model to run the turn on. */
  modelId?: string;
}

/**
 * Starts a follow-up turn on a conversation: registers the turn in the store, carries the earlier turns over, and sends the request to the backend. The follow-up box and a note that arrived after its run had finished both start their turn here.
 */
export function submitFollowUpTurn({
  content,
  displayPromptMarkdown,
  referencePaths,
  rootId,
  agentTaskId,
  displaySource,
  modelId,
}: FollowUpTurnRequest): void {
  const followUpId = crypto.randomUUID();
  const parentAgent = agentStore.getAgent(rootId);
  const previousTaskId = parentAgent
    ? agentStore.getCurrentTurnTaskId(rootId)
    : displaySource?.currentTurnTaskId || displaySource?.agentTaskId || agentTaskId;
  const source = parentAgent || displaySource;
  // Reopened from history there is no store entry yet, so the whole chain on screen must be carried over. Snapshotting only the current turn collapsed an N-turn thread to "Initial request / Follow-up 1".
  const carriedHistory = !parentAgent && displaySource
    ? buildFollowUpHistoryFromViewedDetail(displaySource)
    : [];
  const snapshot = carriedHistory.length > 0 ? carriedHistory[carriedHistory.length - 1] : undefined;

  agentStore.beginFollowUpTurn(followUpId, rootId, snapshot, previousTaskId, source?.taskTitle, { readerStarted: true });
  if (carriedHistory.length > 0) {
    agentStore.setAgentTaskHistory(rootId, carriedHistory);
  } else if (parentAgent) {
    // A chain opened live holds only its newest turn, so the earlier ones are filled in from the backend.
    void seedDurableFollowUpHistory(rootId, followUpId);
  }
  agentStore.updateAgentTaskText(rootId, content);
  agentStore.updateAgentDisplayPromptMarkdown(rootId, displayPromptMarkdown || undefined);
  // Publish these immediately so the result surface shows the submitted follow-up's own References section while work is in progress, rather than waiting for terminal-state hydration from the backend.
  agentStore.setReferencePaths(rootId, referencePaths);
  // A follow-up is not given the earlier run's connection instructions.
  agentStore.setConnectionReferences(rootId, []);
  agentStore.updateOriginalModelId(rootId, modelId);
  agentStore.setSelectedModelId(rootId, undefined);
  api.processAgentTask({
    agent_task: content,
    display_prompt_markdown: displayPromptMarkdown || undefined,
    agent_task_id: followUpId,
    root_task_id: rootId,
    previous_task_id: previousTaskId,
    reference_paths: referencePaths.length > 0 ? referencePaths : undefined,
    model_id: modelId,
  }).catch((error) => {
    console.error('[submitFollowUpTurn] Submit failed:', error);
    agentStore.setError(rootId, 'Failed to submit follow-up');
  });
}
