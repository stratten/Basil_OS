import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  agents: new Map<string, Record<string, unknown>>(),
  listener: null as null | (() => void),
  unsubscribe: vi.fn(),
  submitFollowUpTurn: vi.fn(),
  requestFollowUpLineAdded: vi.fn(),
}));

vi.mock('./agentStore', () => ({
  agentStore: {
    getAgent: (rootId: string) => mocks.agents.get(rootId),
    subscribe: (listener: () => void) => {
      mocks.listener = listener;
      return mocks.unsubscribe;
    },
  },
}));
vi.mock('./followUpPrefillStore', () => ({ requestFollowUpLineAdded: mocks.requestFollowUpLineAdded }));
vi.mock('../app/agents/submitFollowUpTurn', () => ({ submitFollowUpTurn: mocks.submitFollowUpTurn }));

import { holdNoteForFollowUp, resetLateNotes, trackSentNote } from './lateNoteStore';

const note = (text: string, overrides: Record<string, unknown> = {}) => ({ text, referencePaths: [] as string[], modelId: 'model-a', ...overrides });

function guidanceEntry(noteId: string, status: string) {
  return {
    id: `entry-${noteId}`,
    timestamp: '2026-11-17T10:00:00Z',
    detail_kind: 'user_interaction',
    metadata: { user_interaction: { interaction_id: noteId, kind: 'guidance', status, prompt: 'x' } },
  };
}

function setAgent(rootId: string, fields: Record<string, unknown>): void {
  mocks.agents.set(rootId, { executionTimeline: [], isCanceled: false, ...fields });
}

function storeChanged(): void {
  mocks.listener?.();
}

describe('a note that arrives after its run has ended', () => {
  beforeEach(() => {
    resetLateNotes();
    mocks.agents.clear();
    mocks.listener = null;
    mocks.unsubscribe.mockReset();
    mocks.submitFollowUpTurn.mockReset();
    mocks.requestFollowUpLineAdded.mockReset();
  });

  it('is sent as a follow-up at once when the task has already finished', () => {
    setAgent('root-1', { status: 'completed' });

    holdNoteForFollowUp('root-1', 'turn-1', note('Also compare 2025', { referencePaths: ['/tmp/a.txt'] }));

    expect(mocks.submitFollowUpTurn).toHaveBeenCalledTimes(1);
    expect(mocks.submitFollowUpTurn).toHaveBeenCalledWith({
      content: 'Also compare 2025',
      displayPromptMarkdown: 'Also compare 2025',
      referencePaths: ['/tmp/a.txt'],
      rootId: 'root-1',
      agentTaskId: 'turn-1',
      modelId: 'model-a',
    });
  });

  it('waits for the task to finish, then goes out exactly once', () => {
    setAgent('root-1', { status: 'processing' });

    holdNoteForFollowUp('root-1', 'turn-1', note('Also compare 2025'));
    storeChanged();
    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();

    setAgent('root-1', { status: 'completed' });
    storeChanged();
    storeChanged();

    expect(mocks.submitFollowUpTurn).toHaveBeenCalledTimes(1);
    expect(mocks.unsubscribe).toHaveBeenCalled();
  });

  it('combines several waiting notes into one follow-up with their attachments joined once', () => {
    setAgent('root-1', { status: 'processing' });

    holdNoteForFollowUp('root-1', 'turn-1', note('First', { referencePaths: ['/tmp/a.txt', '/tmp/b.txt'] }));
    holdNoteForFollowUp('root-1', 'turn-1', note('Second', { referencePaths: ['/tmp/b.txt'], modelId: 'model-b' }));
    setAgent('root-1', { status: 'completed' });
    storeChanged();

    expect(mocks.submitFollowUpTurn).toHaveBeenCalledTimes(1);
    expect(mocks.submitFollowUpTurn.mock.calls[0][0]).toMatchObject({
      content: 'First\n\nSecond',
      referencePaths: ['/tmp/a.txt', '/tmp/b.txt'],
      modelId: 'model-b',
    });
  });

  it('goes back into the follow-up box instead of being sent when the task failed', () => {
    setAgent('root-1', { status: 'processing' });

    holdNoteForFollowUp('root-1', 'turn-1', note('Try again'));
    setAgent('root-1', { status: 'failed' });
    storeChanged();

    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();
    expect(mocks.requestFollowUpLineAdded).toHaveBeenCalledWith('root-1', 'Try again');
  });

  it('goes back into the follow-up box instead of being sent when the task was stopped', () => {
    setAgent('root-1', { status: 'processing', isCanceled: true });

    holdNoteForFollowUp('root-1', 'turn-1', note('Never mind that'));

    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();
    expect(mocks.requestFollowUpLineAdded).toHaveBeenCalledWith('root-1', 'Never mind that');
  });

  it('goes back into the follow-up box when the conversation is no longer in the store', () => {
    holdNoteForFollowUp('root-gone', 'turn-1', note('Still wanted'));

    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();
    expect(mocks.requestFollowUpLineAdded).toHaveBeenCalledWith('root-gone', 'Still wanted');
  });
});

describe('a note Basil accepted but did not read', () => {
  beforeEach(() => {
    resetLateNotes();
    mocks.agents.clear();
    mocks.listener = null;
    mocks.unsubscribe.mockReset();
    mocks.submitFollowUpTurn.mockReset();
    mocks.requestFollowUpLineAdded.mockReset();
  });

  it('becomes a follow-up when it is recorded as not delivered and the task finishes', () => {
    setAgent('root-1', { status: 'processing', executionTimeline: [guidanceEntry('note-1', 'waiting')] });
    trackSentNote('note-1', 'root-1', 'turn-1', note('Mind the date range'));

    storeChanged();
    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();

    setAgent('root-1', { status: 'completed', executionTimeline: [guidanceEntry('note-1', 'canceled')] });
    storeChanged();
    storeChanged();

    expect(mocks.submitFollowUpTurn).toHaveBeenCalledTimes(1);
    expect(mocks.submitFollowUpTurn.mock.calls[0][0]).toMatchObject({ content: 'Mind the date range', rootId: 'root-1' });
  });

  it('is left alone once Basil has read it, even though the task then finishes', () => {
    setAgent('root-1', { status: 'processing', executionTimeline: [guidanceEntry('note-1', 'waiting')] });
    trackSentNote('note-1', 'root-1', 'turn-1', note('Mind the date range'));

    setAgent('root-1', { status: 'processing', executionTimeline: [guidanceEntry('note-1', 'resolved')] });
    storeChanged();
    setAgent('root-1', { status: 'completed', executionTimeline: [guidanceEntry('note-1', 'resolved')] });
    storeChanged();

    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();
    expect(mocks.requestFollowUpLineAdded).not.toHaveBeenCalled();
    expect(mocks.unsubscribe).toHaveBeenCalled();
  });

  it('is not guessed at from the task finishing before its record appears', () => {
    setAgent('root-1', { status: 'processing', executionTimeline: [] });
    trackSentNote('note-1', 'root-1', 'turn-1', note('Mind the date range'));

    setAgent('root-1', { status: 'completed', executionTimeline: [] });
    storeChanged();

    expect(mocks.submitFollowUpTurn).not.toHaveBeenCalled();
  });
});
