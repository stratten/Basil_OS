import { beforeEach, describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { loadComposerDraft, rememberComposerHtml, resetComposerDrafts } from '../composerDraftStore';
import { AgentStore } from './websocketHandlers';

function startedEvent(): WSEvent {
  return {
    event_type: 'agent_progress_update',
    agent_task_id: 'voice-follow-up',
    root_task_id: 'root-1',
    timeline_entry: {
      id: 'step-1',
      type: 'step',
      timestamp: '2026-10-28T16:00:00Z',
      content: 'Working on it',
      metadata: { progress_status: 'in_progress' },
    },
  };
}

describe('the unsent follow-up draft once a follow-up turn begins', () => {
  beforeEach(() => resetComposerDrafts());

  it('is dropped when the follow-up is started by the store, however it was sent', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.beginFollowUpTurn('turn-2', 'root-1');

    expect(loadComposerDraft('follow-up', 'root-1')).toBeUndefined();
  });

  it('is dropped when a follow-up first arrives as a live event, as a voice follow-up does', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.handleWSEvent(startedEvent());

    expect(loadComposerDraft('follow-up', 'root-1')).toBeUndefined();
  });

  it('is dropped under the turn id the host used as well as under the chain root', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'under the root', true);
    rememberComposerHtml('follow-up', 'turn-1', 'under a turn id', true);

    store.beginFollowUpTurn('turn-2', 'root-1', undefined, 'turn-1');
    store.beginFollowUpTurn('turn-3', 'turn-1');

    expect(loadComposerDraft('follow-up', 'root-1')).toBeUndefined();
    expect(loadComposerDraft('follow-up', 'turn-1')).toBeUndefined();
  });

  it('is kept when the same turn is merely seen again, and for other chains and for notes', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.beginFollowUpTurn('turn-2', 'root-1');
    rememberComposerHtml('follow-up', 'root-1', 'typed after the turn began', true);
    rememberComposerHtml('follow-up', 'other-chain', 'a different chain', true);
    rememberComposerHtml('note', 'root-1', 'a note for the running turn', true);

    store.beginFollowUpTurn('turn-2', 'root-1');

    expect(loadComposerDraft('follow-up', 'root-1')?.html).toBe('typed after the turn began');
    expect(loadComposerDraft('follow-up', 'other-chain')?.html).toBe('a different chain');
    expect(loadComposerDraft('note', 'root-1')?.html).toBe('a note for the running turn');
  });
});
