import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../../types';

const mocks = vi.hoisted(() => ({
  continueSession: vi.fn(),
  addClarification: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  continueSession: mocks.continueSession,
  addClarification: mocks.addClarification,
}));

import { agentStore } from '../../store/agentStore';
import { answerQuestionWithNote, checkpointAcceptsTypedNote, typedNoteAnswer } from './answerWithNote';

const question: CheckpointData = { checkpoint_id: 'cp-1', prompt: 'How should I proceed?', input_type: 'data' };

function waitingStore(checkpoint: CheckpointData) {
  agentStore.registerAgent('task-1');
  agentStore.updateStatus('task-1', 'processing');
  agentStore.showCheckpoint('task-1', checkpoint);
  agentStore.dismissCheckpoint('task-1');
}

beforeEach(() => {
  mocks.continueSession.mockReset().mockResolvedValue({ success: true });
  mocks.addClarification.mockReset().mockResolvedValue({ success: true });
  agentStore.removeAgent('task-1');
});

describe('checkpointAcceptsTypedNote', () => {
  it('accepts ordinary questions and refuses ones whose answer is not free text', () => {
    expect(checkpointAcceptsTypedNote(question)).toBe(true);
    expect(checkpointAcceptsTypedNote({ ...question, metadata: { source: 'clarification' } })).toBe(true);
    for (const source of ['provider_user_input', 'provider_target_authorization', 'browser_permission_repair']) {
      expect(checkpointAcceptsTypedNote({ ...question, metadata: { source } })).toBe(false);
    }
    expect(checkpointAcceptsTypedNote(undefined)).toBe(false);
  });
});

describe('typedNoteAnswer', () => {
  it('sends plain text as typed, trimmed', () => {
    expect(typedNoteAnswer(question, '  Use the second draft  ')).toBe('Use the second draft');
  });

  it('wraps the note as the Other answer for choice and confirmation questions', () => {
    expect(typedNoteAnswer({ ...question, input_type: 'choice' }, 'Neither')).toBe('Other: Neither');
    expect(typedNoteAnswer({ ...question, input_type: 'confirmation' }, 'Wait, not yet')).toBe('Other: Wait, not yet');
  });

  it('requires a number for a numeric question', () => {
    const numeric: CheckpointData = { ...question, value_kind: 'numeric' };
    expect(typedNoteAnswer(numeric, '1,200')).toBe('1,200');
    expect(() => typedNoteAnswer(numeric, 'about twelve')).toThrow('This question needs a number.');
  });
});

describe('answerQuestionWithNote', () => {
  it('answers through the continue route, remembers the answer, and lets the run show as resuming', async () => {
    waitingStore(question);

    await answerQuestionWithNote('task-1', question, 'Use the second draft');

    expect(mocks.continueSession).toHaveBeenCalledWith('task-1', 'Use the second draft');
    expect(agentStore.isPromptAnswered('task-1', 'cp-1')).toBe(true);
    expect(agentStore.getAgent('task-1')?.currentCheckpoint).toBeUndefined();
  });

  it('answers a clarification through the clarification route against the session task', async () => {
    const clarification: CheckpointData = {
      ...question,
      session_agent_task_id: 'session-9',
      metadata: { source: 'clarification' },
    };
    waitingStore(clarification);

    await answerQuestionWithNote('task-1', clarification, 'The Paris one');

    expect(mocks.addClarification).toHaveBeenCalledWith('session-9', 'The Paris one');
    expect(mocks.continueSession).not.toHaveBeenCalled();
  });

  it('keeps the question open and rethrows when delivery fails', async () => {
    waitingStore(question);
    mocks.continueSession.mockRejectedValue(new Error('Basil is offline'));

    await expect(answerQuestionWithNote('task-1', question, 'Use the second draft')).rejects.toThrow('Basil is offline');

    const agent = agentStore.getAgent('task-1')!;
    expect(agent.status).toBe('awaitingInput');
    expect(agent.currentCheckpoint?.checkpoint_id).toBe('cp-1');
    expect(agent.showCheckpointPrompt).toBe(false);
    expect(agentStore.isPromptAnswered('task-1', 'cp-1')).toBe(false);
  });

  it('refuses an empty note without calling the backend', async () => {
    waitingStore(question);

    await expect(answerQuestionWithNote('task-1', question, '   ')).rejects.toThrow('Type an answer first.');

    expect(mocks.continueSession).not.toHaveBeenCalled();
  });
});
