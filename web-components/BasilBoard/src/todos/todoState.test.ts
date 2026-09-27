import { describe, expect, it } from 'vitest';
import type { TodoItemDetail, TodoItemSummary, TodoWorkspaceResultEvent } from '../contracts';
import {
  applyOptimisticConflictReplacement,
  applyWorkspaceError,
  applyWorkspaceResult,
  appendUserMessage,
  clearWorkspace,
  createWorkspaceState,
  filterToStatuses,
} from './todoState';

function summary(overrides: Partial<TodoItemSummary> = {}): TodoItemSummary {
  return {
    id: 'todo-1', title: 'Draft the follow-up', status: 'open', responsibility: 'user', priority: 'normal',
    due_at: null, revision: 1, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    attention: { needs_attention: false }, ...overrides,
  };
}

function detail(overrides: Partial<TodoItemDetail> = {}): TodoItemDetail {
  return {
    ...summary(overrides),
    description: '', notes: '', idempotency_key: null, created_by_kind: 'user', created_by_id: null,
    sources: [], references: [], worker_attempts: [], ...overrides,
  };
}

describe('filterToStatuses', () => {
  it('maps the inbox filter to the candidate status', () => {
    expect(filterToStatuses('inbox')).toEqual(['candidate']);
  });

  it('maps the all filter to no status restriction', () => {
    expect(filterToStatuses('all')).toBeUndefined();
  });

  it('maps the open filter to the open/in-progress/ready-for-review superset', () => {
    expect(filterToStatuses('open')).toEqual(['open', 'in_progress', 'ready_for_review']);
  });

  it('passes the remaining specific filters through as a single-status list', () => {
    expect(filterToStatuses('in_progress')).toEqual(['in_progress']);
    expect(filterToStatuses('ready_for_review')).toEqual(['ready_for_review']);
    expect(filterToStatuses('completed')).toEqual(['completed']);
  });
});

describe('applyOptimisticConflictReplacement', () => {
  it('replaces the matching item in place', () => {
    const items = [summary({ id: 'a', title: 'A' }), summary({ id: 'b', title: 'B' })];
    const latest = detail({ id: 'b', title: 'B updated', revision: 2 });

    const result = applyOptimisticConflictReplacement(items, latest);

    expect(result).toHaveLength(2);
    expect(result.find((item) => item.id === 'b')?.title).toBe('B updated');
    expect(result.find((item) => item.id === 'a')?.title).toBe('A');
  });

  it('prepends the item when it is not already in the list', () => {
    const items = [summary({ id: 'a' })];
    const latest = detail({ id: 'new-item', title: 'Just created' });

    const result = applyOptimisticConflictReplacement(items, latest);

    expect(result[0].id).toBe('new-item');
    expect(result).toHaveLength(2);
  });

  it('handles an empty starting list', () => {
    const result = applyOptimisticConflictReplacement([], detail({ id: 'only' }));
    expect(result).toEqual([detail({ id: 'only' })]);
  });
});

describe('workspace state transitions', () => {
  it('creates an empty workspace with no pending request', () => {
    const state = createWorkspaceState('ws-1');
    expect(state).toEqual({ workspaceId: 'ws-1', pendingRequestId: null, transcript: [] });
  });

  it('appendUserMessage sets pendingRequestId and appends a user transcript entry', () => {
    const state = createWorkspaceState('ws-1');
    const next = appendUserMessage(state, 'req-1', 'What is the status?');

    expect(next.pendingRequestId).toBe('req-1');
    expect(next.transcript).toEqual([{ id: 'req-1', role: 'user', content: 'What is the status?' }]);
  });

  it('applyWorkspaceResult appends the assistant reply and clears pendingRequestId when ids match', () => {
    const withPending = appendUserMessage(createWorkspaceState('ws-1'), 'req-1', 'hi');
    const event: TodoWorkspaceResultEvent = {
      event_type: 'todo_workspace_result', workspace_id: 'ws-1', request_id: 'req-1',
      agent_task_id: 'task-1', status: 'completed', summary: 'Done.', selected_todo_ids: ['todo-1'],
    };

    const next = applyWorkspaceResult(withPending, event);

    expect(next.pendingRequestId).toBeNull();
    expect(next.transcript).toHaveLength(2);
    expect(next.transcript[1]).toEqual({ id: 'req-1-assistant', role: 'assistant', content: 'Done.' });
  });

  it('applyWorkspaceResult ignores a mismatched workspace_id (stale/foreign event)', () => {
    const withPending = appendUserMessage(createWorkspaceState('ws-1'), 'req-1', 'hi');
    const event: TodoWorkspaceResultEvent = {
      event_type: 'todo_workspace_result', workspace_id: 'ws-OTHER', request_id: 'req-1',
      agent_task_id: 'task-1', status: 'completed', summary: 'Done.', selected_todo_ids: [],
    };

    const next = applyWorkspaceResult(withPending, event);

    expect(next).toBe(withPending); // unchanged
  });

  it('applyWorkspaceResult ignores a mismatched request_id (a stale reply after "New conversation")', () => {
    const withPending = appendUserMessage(createWorkspaceState('ws-1'), 'req-2', 'second question');
    const staleEvent: TodoWorkspaceResultEvent = {
      event_type: 'todo_workspace_result', workspace_id: 'ws-1', request_id: 'req-1',
      agent_task_id: 'task-1', status: 'completed', summary: 'Stale reply for the first question.',
      selected_todo_ids: [],
    };

    const next = applyWorkspaceResult(withPending, staleEvent);

    expect(next.pendingRequestId).toBe('req-2');
    expect(next.transcript).toHaveLength(1); // the stale reply was not appended
  });

  it('applyWorkspaceError appends an error transcript entry and clears pendingRequestId', () => {
    const withPending = appendUserMessage(createWorkspaceState('ws-1'), 'req-1', 'hi');

    const next = applyWorkspaceError(withPending, 'ws-1', 'req-1', 'delegate_todo_work is only available from a To-Do workspace turn');

    expect(next.pendingRequestId).toBeNull();
    expect(next.transcript[1]).toEqual({
      id: 'req-1-error', role: 'error',
      content: 'delegate_todo_work is only available from a To-Do workspace turn',
    });
  });

  it('applyWorkspaceError ignores a mismatched workspace or request id', () => {
    const withPending = appendUserMessage(createWorkspaceState('ws-1'), 'req-1', 'hi');
    const next = applyWorkspaceError(withPending, 'ws-1', 'req-DIFFERENT', 'ignored error');
    expect(next).toBe(withPending);
  });

  it('clearWorkspace returns a brand-new empty state for a new workspace id, discarding the old transcript', () => {
    const populated = appendUserMessage(createWorkspaceState('ws-1'), 'req-1', 'hi');
    const cleared = clearWorkspace('ws-2');
    expect(cleared).toEqual({ workspaceId: 'ws-2', pendingRequestId: null, transcript: [] });
    expect(populated.transcript).toHaveLength(1); // original state object untouched
  });
});
