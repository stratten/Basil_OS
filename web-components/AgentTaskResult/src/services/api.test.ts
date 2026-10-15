import { afterEach, describe, expect, it, vi } from 'vitest';
import { archiveAgentTask, getTodoOriginDetail, listAgentTasks, searchAgentTasks, setBaseUrl, submitApprovalDecision, unarchiveAgentTask } from './api';

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

describe('archive API helpers', () => {
  function stubFetch(payload: unknown) {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(
      JSON.stringify(payload),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8123);
    return fetchMock;
  }

  it('omits the archived parameter by default and sends archived=true on request for history and search', async () => {
    const fetchMock = stubFetch({ agentTasks: [], total_count: 0, has_more: false });

    await listAgentTasks(25, 0);
    await listAgentTasks(25, 0, undefined, { archived: true });
    await searchAgentTasks('invoice', 25, 0);
    await searchAgentTasks('invoice', 25, 0, { archived: true });

    const urls = fetchMock.mock.calls.map(call => String(call[0]));
    expect(urls[0]).not.toContain('archived');
    expect(urls[1]).toContain('archived=true');
    expect(urls[2]).not.toContain('archived');
    expect(urls[3]).toContain('archived=true');
    expect(urls[3]).toContain('query=invoice');
  });

  it('posts to the archive and unarchive routes of the chain', async () => {
    const fetchMock = stubFetch({ success: true });

    await archiveAgentTask('task-1');
    await unarchiveAgentTask('task-1');

    expect(fetchMock).toHaveBeenNthCalledWith(1, 'http://localhost:8123/api/v1/agent-tasks/task-1/archive', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, 'http://localhost:8123/api/v1/agent-tasks/task-1/unarchive', expect.objectContaining({ method: 'POST' }));
  });
});
