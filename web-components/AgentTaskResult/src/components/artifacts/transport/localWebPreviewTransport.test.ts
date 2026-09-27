import { describe, expect, it, vi } from 'vitest';
import { createLocalWebPreviewTransport } from './localWebPreviewTransport';

function armFetch(responseBody: Record<string, unknown>) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => responseBody,
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('local web preview transport session parsing', () => {
  it('maps snake_case lifecycle fields into the typed camelCase session DTO', async () => {
    armFetch({
      session_id: 'session-1',
      agent_task_id: 'task-1',
      artifact_id: 'artifact-1',
      status: 'running',
      url: 'http://127.0.0.1:4173',
      host: '127.0.0.1',
      port: 4173,
      pid: 4242,
      last_error: null,
      command: 'npm',
      args: ['run', 'dev'],
      cwd: '/private/project',
      created_at: 1700000000,
      stopped_at: null,
    });
    const transport = createLocalWebPreviewTransport(() => 'http://localhost:9000');

    const session = await transport.getSession({ agentTaskId: 'task-1', artifactId: 'artifact-1', sessionId: 'session-1' });

    expect(session).toMatchObject({
      command: 'npm',
      args: ['run', 'dev'],
      cwd: '/private/project',
      createdAt: 1700000000,
      stoppedAt: null,
    });
  });

  it('defaults args to an empty array when the backend omits or sends a non-array value', async () => {
    armFetch({
      session_id: 'session-2',
      status: 'error',
      url: 'http://127.0.0.1:4173',
      host: '127.0.0.1',
      port: 4173,
      pid: null,
      last_error: 'Server did not start listening.',
      command: 'python3',
      args: 'not-an-array',
      cwd: '/private/project',
      created_at: 1700000000,
      stopped_at: 1700000005,
    });
    const transport = createLocalWebPreviewTransport(() => 'http://localhost:9000');

    const session = await transport.getSession({ agentTaskId: 'task-1', artifactId: 'artifact-1', sessionId: 'session-2' });

    expect(session.args).toEqual([]);
    expect(session.stoppedAt).toBe(1700000005);
  });

  it('contains an unrecognized session state as an error', async () => {
    armFetch({
      session_id: 'session-3',
      status: 'unknown',
      url: 'http://127.0.0.1:4173',
      host: '127.0.0.1',
      port: 4173,
      pid: null,
      last_error: null,
      command: 'python3',
      args: [],
      cwd: '/private/project',
      created_at: 1700000000,
      stopped_at: null,
    });
    const transport = createLocalWebPreviewTransport(() => 'http://localhost:9000');

    const session = await transport.getSession({ agentTaskId: 'task-1', artifactId: 'artifact-1', sessionId: 'session-3' });

    expect(session.status).toBe('error');
  });
});
