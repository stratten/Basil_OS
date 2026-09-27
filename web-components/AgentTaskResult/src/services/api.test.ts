import { afterEach, describe, expect, it, vi } from 'vitest';
import { getTodoOriginDetail, setBaseUrl, submitApprovalDecision } from './api';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('submitApprovalDecision', () => {
  it('posts ownership and revision to the current Agent Task approval route', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, message: 'approved' }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8123);

    await submitApprovalDecision({
      approval_id: 'approval-1',
      command: 'pwd',
      approved: true,
      remember_choice: false,
      agent_task_id: 'child-turn',
      expected_revision: 2,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8123/api/v1/agent-tasks/approval/decide',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('"agent_task_id":"child-turn"'),
      }),
    );
  });
});

describe('getTodoOriginDetail', () => {
  it('fetches an encoded To-Do identifier and returns its source lineage', async () => {
    const payload = {
      id: 'todo/a',
      sources: [{
        source_kind: 'meeting_analysis_proposal',
        source_id: 'meeting-1:analysis.json:proposal-1',
        source_locator: { meeting_id: 'meeting-1' },
      }],
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify(payload),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8123);

    await expect(getTodoOriginDetail('todo/a')).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8123/api/v1/todos/items/todo%2Fa',
      expect.objectContaining({ method: 'GET' }),
    );
  });
});
