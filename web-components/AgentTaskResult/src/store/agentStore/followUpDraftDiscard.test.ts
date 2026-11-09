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

  it('is dropped when the reader sends a follow-up, typed or by voice', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.beginFollowUpTurn('turn-2', 'root-1', undefined, undefined, undefined, { readerStarted: true });

    expect(loadComposerDraft('follow-up', 'root-1')).toBeUndefined();
  });

  it('is kept when a turn first arrives as a live event, because the window cannot tell who started it', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.handleWSEvent(startedEvent());

    expect(loadComposerDraft('follow-up', 'root-1')?.html).toBe('a half-written question');
  });

  it('is kept when a turn begins without the reader having sent it, the default for hydration and any other caller', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.beginFollowUpTurn('turn-2', 'root-1');

    expect(loadComposerDraft('follow-up', 'root-1')?.html).toBe('a half-written question');
  });

  it('is kept when a turn is both background and flagged as the reader\'s, since background wins', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'a half-written question', true);

    store.beginFollowUpTurn('turn-2', 'root-1', undefined, undefined, undefined, { background: true, readerStarted: true });

    expect(loadComposerDraft('follow-up', 'root-1')?.html).toBe('a half-written question');
  });

  it('is dropped under the turn id the host used as well as under the chain root', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    rememberComposerHtml('follow-up', 'root-1', 'under the root', true);
    rememberComposerHtml('follow-up', 'turn-1', 'under a turn id', true);

    store.beginFollowUpTurn('turn-2', 'root-1', undefined, 'turn-1', undefined, { readerStarted: true });
    store.beginFollowUpTurn('turn-3', 'turn-1', undefined, undefined, undefined, { readerStarted: true });

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
