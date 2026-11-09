import { beforeEach, describe, expect, it } from 'vitest';
import type { WSEvent } from '../../types';
import { loadComposerDraft, rememberComposerHtml, resetComposerDrafts } from '../composerDraftStore';
import { isBackgroundOriginType } from './backgroundOrigin';
import { AgentStore } from './websocketHandlers';

const originEvent = (taskId: string, originType: string, rootId?: string): WSEvent => ({
  event_type: 'agent_task_origin',
  agent_task_id: taskId,
  root_task_id: rootId,
  origin_type: originType,
  origin_id: 'origin-1',
} as WSEvent);

const progressEvent = (taskId: string, rootId?: string): WSEvent => ({
  event_type: 'agent_progress_update',
  agent_task_id: taskId,
  root_task_id: rootId,
  timeline_entry: { id: `step-${taskId}`, type: 'step', timestamp: '2026-11-03T20:00:00Z', content: 'Working', metadata: { progress_status: 'in_progress' } },
} as WSEvent);

describe('runs Basil starts on its own', () => {
  beforeEach(() => resetComposerDrafts());

  it('names scheduled runs and Basil continuing its own task, and nothing else, as background origins', () => {
    expect(isBackgroundOriginType('scheduled_task')).toBe(true);
    expect(isBackgroundOriginType('agent_follow_up')).toBe(true);
    expect(isBackgroundOriginType('conversation')).toBe(false);
    expect(isBackgroundOriginType(undefined)).toBe(false);
  });

  it('registers a new scheduled run without selecting it while nothing is open, such as in the schedule editor', () => {
    const store = new AgentStore();

    store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task'));
    store.handleWSEvent(progressEvent('scheduled-run'));

    expect(store.getAgent('scheduled-run')).toBeDefined();
    expect(store.getSelectedAgentId()).toBeNull();
  });

  // The backend announces a scheduled run with scheduled_agent_task_run_started, carrying the run's task id, before it sends agent_task_origin.
  const runStartedEvent = (taskId: string): WSEvent => ({
    event_type: 'scheduled_agent_task_run_started',
    scheduled_agent_task_id: 'schedule-1',
    run_id: 'run-1',
    agent_task_id: taskId,
    title: 'Inbox check',
  } as WSEvent);

  it('does not select a scheduled run announced by its run-started event while nothing is open, such as in the schedule editor', () => {
    const store = new AgentStore();

    store.handleWSEvent(runStartedEvent('scheduled-run'));
    store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task'));
    store.handleWSEvent(progressEvent('scheduled-run'));

    expect(store.getAgent('scheduled-run')).toBeDefined();
    expect(store.getSelectedAgentId()).toBeNull();
  });

  it('does not select a scheduled run announced by its run-started event while a history task is open', () => {
    const store = new AgentStore();
    store.registerAgent('viewed');
    store.deselectAgent();

    store.handleWSEvent(runStartedEvent('scheduled-run'));
    store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task'));

    expect(store.getSelectedAgentId()).toBeNull();
  });

  it('ignores the run-completed and missed envelopes for a run this window never saw', () => {
    const store = new AgentStore();

    store.handleWSEvent({ event_type: 'scheduled_agent_task_run_completed', scheduled_agent_task_id: 'schedule-1', run_id: 'run-1', agent_task_id: 'unseen-run' } as WSEvent);
    store.handleWSEvent({ event_type: 'scheduled_agent_task_missed', scheduled_agent_task_id: 'schedule-1', run_id: 'run-2', agent_task_id: 'unseen-run-2' } as WSEvent);

    expect(store.getAgent('unseen-run')).toBeUndefined();
    expect(store.getAgent('unseen-run-2')).toBeUndefined();
    expect(store.getSelectedAgentId()).toBeNull();
  });

  it('leaves the selected task alone when a scheduled run starts', () => {
    const store = new AgentStore();
    store.registerAgent('viewed');

    store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task'));

    expect(store.getAgent('scheduled-run')).toBeDefined();
    expect(store.getSelectedAgentId()).toBe('viewed');
  });

  it('keeps the view and the unsent follow-up text when a scheduled run continues another chain', () => {
    const store = new AgentStore();
    store.registerAgent('viewed');
    store.registerAgent('chain-root');
    store.selectAgent('viewed');
    rememberComposerHtml('follow-up', 'chain-root', 'half-written question', true);

    store.handleWSEvent(originEvent('chained-run', 'scheduled_task', 'chain-root'));
    store.handleWSEvent(progressEvent('chained-run', 'chain-root'));

    expect(store.getSelectedAgentId()).toBe('viewed');
    expect(loadComposerDraft('follow-up', 'chain-root')).toBeDefined();
    expect(store.getAgent('chain-root')?.status).toBe('processing');
  });

  it('does not select a chain that Basil continues on its own, and keeps the draft', () => {
    const store = new AgentStore();
    store.registerAgent('viewed');
    rememberComposerHtml('follow-up', 'chain-root', 'my draft', true);

    store.handleWSEvent(originEvent('basil-turn', 'agent_follow_up', 'chain-root'));

    expect(store.getSelectedAgentId()).toBe('viewed');
    expect(loadComposerDraft('follow-up', 'chain-root')).toBeDefined();
  });

  it('keeps the reader\'s own active turn as the active one when Basil starts a turn in the same chain', () => {
    const store = new AgentStore();
    store.registerAgent('chain-root');
    store.beginFollowUpTurn('user-turn', 'chain-root');

    store.handleWSEvent(originEvent('basil-turn', 'agent_follow_up', 'chain-root'));

    expect((store as unknown as { activeFollowUpByParent: Map<string, string> }).activeFollowUpByParent.get('chain-root')).toBe('user-turn');
  });

  it('still selects the chain for a follow-up that first arrives as a live event, but keeps the unsent text', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.registerAgent('other');
    store.selectAgent('other');
    rememberComposerHtml('follow-up', 'root-1', 'my question', true);

    store.handleWSEvent(progressEvent('voice-follow-up', 'root-1'));

    expect(store.getSelectedAgentId()).toBe('root-1');
    expect(loadComposerDraft('follow-up', 'root-1')?.html).toBe('my question');
  });

  it('still clears the draft for a follow-up the reader sent, and selects the chain', () => {
    const store = new AgentStore();
    store.registerAgent('root-1');
    store.registerAgent('other');
    store.selectAgent('other');
    rememberComposerHtml('follow-up', 'root-1', 'my question', true);

    store.registerFollowUp('voice-follow-up', 'root-1');

    expect(store.getSelectedAgentId()).toBe('root-1');
    expect(loadComposerDraft('follow-up', 'root-1')).toBeUndefined();
  });

  describe('a scheduled run on the chain the reader is typing into', () => {
    const draftText = 'half-written follow-up';

    const readerIsTypingIntoChain = (store: AgentStore) => {
      store.registerAgent('chain-root');
      store.selectAgent('chain-root');
      rememberComposerHtml('follow-up', 'chain-root', draftText, true);
    };

    it('keeps the draft when the origin event arrives first', () => {
      const store = new AgentStore();
      readerIsTypingIntoChain(store);

      store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task', 'chain-root'));
      store.handleWSEvent(progressEvent('scheduled-run', 'chain-root'));

      expect(loadComposerDraft('follow-up', 'chain-root')?.html).toBe(draftText);
    });

    it('keeps the draft when the origin event was missed and the first event seen is a progress event', () => {
      const store = new AgentStore();
      readerIsTypingIntoChain(store);

      store.handleWSEvent(progressEvent('scheduled-run', 'chain-root'));
      store.handleWSEvent(progressEvent('scheduled-run', 'chain-root'));

      expect(loadComposerDraft('follow-up', 'chain-root')?.html).toBe(draftText);
      expect(store.getAgent('chain-root')?.status).toBe('processing');
    });

    it('keeps the draft in a window that loaded mid-run and sees the run for the first time through a step event', () => {
      const store = new AgentStore();
      readerIsTypingIntoChain(store);

      store.handleWSEvent({
        event_type: 'dynamic_step_added',
        agent_task_id: 'scheduled-run',
        root_task_id: 'chain-root',
        step_id: 'dynamic_1',
        status: 'in_progress',
        timestamp: '2026-11-08T16:48:35.331606+00:00',
      } as WSEvent);

      expect(loadComposerDraft('follow-up', 'chain-root')?.html).toBe(draftText);
    });

    it('keeps the draft when the page is reloaded mid-run and the same run is registered a second time', () => {
      // The composer drafts outlive the store that registered the run, as they do across a reload of the page, so a second store stands in for the reloaded page that never saw the origin event.
      const firstPage = new AgentStore();
      readerIsTypingIntoChain(firstPage);
      firstPage.handleWSEvent(originEvent('scheduled-run', 'scheduled_task', 'chain-root'));
      firstPage.handleWSEvent(progressEvent('scheduled-run', 'chain-root'));

      const reloadedPage = new AgentStore();
      reloadedPage.registerAgent('chain-root');
      reloadedPage.handleWSEvent(progressEvent('scheduled-run', 'chain-root'));

      expect(loadComposerDraft('follow-up', 'chain-root')?.html).toBe(draftText);
    });

    it('keeps the draft when the chain is hydrated from the backend mid-run', () => {
      const store = new AgentStore();
      readerIsTypingIntoChain(store);

      store.beginFollowUpTurn('scheduled-run', 'chain-root', undefined, 'previous-turn');

      expect(loadComposerDraft('follow-up', 'chain-root')?.html).toBe(draftText);
      expect(store.getAgent('chain-root')?.currentTurnTaskId).toBe('scheduled-run');
    });

    it('still lets the reader\'s own send clear the draft while the scheduled run is in flight', () => {
      const store = new AgentStore();
      readerIsTypingIntoChain(store);
      store.handleWSEvent(originEvent('scheduled-run', 'scheduled_task', 'chain-root'));

      store.beginFollowUpTurn('reader-turn', 'chain-root', undefined, undefined, undefined, { readerStarted: true });

      expect(loadComposerDraft('follow-up', 'chain-root')).toBeUndefined();
    });
  });

  it('still selects a new task that arrives as a live event with no origin, as before', () => {
    const store = new AgentStore();

    store.handleWSEvent(progressEvent('fresh-task'));

    expect(store.getSelectedAgentId()).toBe('fresh-task');
  });
});
