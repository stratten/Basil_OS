import type { CheckpointData } from '../../types';
import * as api from '../../services/api';
import { agentStore } from '../../store/agentStore';
import { formatCheckpointAnswer, isValidNumericAnswer } from '../checkpoint/checkpointAnswer';

/** Question sources whose answer is not free text: a provider form has named fields, a target authorization resolves the reply as a fixed token, and a browser permission repair is fixed by the user outside Basil. */
const NON_TEXT_SOURCES: ReadonlySet<string> = new Set(['provider_user_input', 'provider_target_authorization', 'browser_permission_repair']);

/** True when a typed note can stand in for the answer to this question. The note box offers to answer only then. */
export function checkpointAcceptsTypedNote(checkpoint: CheckpointData | undefined): checkpoint is CheckpointData {
  if (!checkpoint) return false;
  const source = checkpoint.metadata?.source;
  return !(typeof source === 'string' && NON_TEXT_SOURCES.has(source));
}

/** The text the backend receives for a typed note, in the same shape the question card sends. A choice or confirmation takes it as the Other answer, and a numeric question needs a number. */
export function typedNoteAnswer(checkpoint: CheckpointData, note: string): string {
  const text = note.trim();
  if (checkpoint.input_type === 'choice' || checkpoint.input_type === 'confirmation') {
    return formatCheckpointAnswer({ selectedValues: [], otherText: text, labeled: true });
  }
  if (checkpoint.input_type === 'data' && checkpoint.value_kind === 'numeric' && !isValidNumericAnswer(text)) {
    throw new Error('This question needs a number.');
  }
  return text;
}

/**
 * Sends a typed note as the answer to the question the run is waiting on, the same way the question card sends one: the answer is remembered at once, the run shows as resuming, and a failed delivery reopens the question so nothing is lost.
 */
export async function answerQuestionWithNote(agentTaskId: string, checkpoint: CheckpointData, note: string): Promise<void> {
  const response = typedNoteAnswer(checkpoint, note);
  if (!response) throw new Error('Type an answer first.');
  const sessionAgentTaskId = checkpoint.session_agent_task_id || agentTaskId;
  const isClarification = checkpoint.metadata?.source === 'clarification';
  const step = isClarification ? 'Processing clarification...' : 'Resuming...';
  agentStore.beginCheckpointAnswer(agentTaskId, checkpoint.checkpoint_id, step);
  agentStore.updateProgressStep(agentTaskId, step, true, false);
  try {
    if (isClarification) await api.addClarification(sessionAgentTaskId, response);
    else await api.continueSession(sessionAgentTaskId, response);
  } catch (error) {
    agentStore.reopenCheckpointAfterFailedAnswer(agentTaskId, checkpoint);
    agentStore.dismissCheckpoint(agentTaskId);
    agentStore.updateStatus(agentTaskId, 'awaitingInput');
    throw error;
  }
  agentStore.settleAnsweredCheckpoint(agentTaskId, checkpoint.checkpoint_id, step);
}
