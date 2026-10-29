import { afterEach, describe, expect, it, vi } from 'vitest';
import { cancelSession, setBaseUrl } from './api';

describe('cancelSession', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('issues one REST cancellation request and decodes the cancellation receipt', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      message: 'Task canceled',
      finalized_via_agent: false,
      agent_task_id: 'task-1',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8000);

    await expect(cancelSession('task-1', 'User canceled')).resolves.toEqual({
      success: true,
      message: 'Task canceled',
      finalized_via_agent: false,
      agent_task_id: 'task-1',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/agent-tasks/sessions/task-1/cancel',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ reason: 'User requested cancellation' }),
      }),
    );
  });

  it('surfaces a network failure after the shared request retry', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('offline'));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8000);

    await expect(cancelSession('task-2')).rejects.toThrow('offline');
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('allows repeated idempotent cancellation requests', async () => {
    const response = {
      success: true,
      message: 'Task canceled',
      finalized_via_agent: false,
      agent_task_id: 'task-3',
    };
    const fetchMock = vi.fn().mockImplementation(
      () => Promise.resolve(new Response(JSON.stringify(response), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })),
    );
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8000);

    await cancelSession('task-3');
    await cancelSession('task-3');

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
