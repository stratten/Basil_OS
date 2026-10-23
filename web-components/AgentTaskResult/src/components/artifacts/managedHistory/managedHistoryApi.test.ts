import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { setBaseUrl } from '../../../services/api';
import {
  getManagedFileVersionContent,
  listManagedFileVersions,
  restoreManagedFileVersion,
} from './managedHistoryApi';

const originalFetch = globalThis.fetch;

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  setBaseUrl(8000);
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe('managedHistoryApi', () => {
  it('requests versions through the initialized shared client, never a file: URL', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      canonical_path: '/tmp/a b.md',
      versions: [],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await listManagedFileVersions('/tmp/a b.md');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const requestedUrl = fetchMock.mock.calls[0][0] as string;
    expect(requestedUrl).toBe(
      'http://localhost:8000/api/v1/agent-tasks/managed-file-history/versions?canonical_path=%2Ftmp%2Fa%20b.md',
    );
    expect(requestedUrl.startsWith('file:')).toBe(false);
  });

  it('maps root_task_id and agent_task_id provenance onto each returned version', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      canonical_path: '/tmp/report.md',
      versions: [
        {
          id: 'change-1',
          root_task_id: 'root-1',
          agent_task_id: 'follow-up-1',
          canonical_path: '/tmp/report.md',
          operation: 'overwrite',
          origin: 'model',
          post_image_size_bytes: 42,
          restores_change_id: null,
          created_at: '2026-08-16T00:00:00Z',
          applied_at: '2026-08-16T00:00:01Z',
        },
      ],
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const versions = await listManagedFileVersions('/tmp/report.md');

    expect(versions).toEqual([
      {
        id: 'change-1',
        rootTaskId: 'root-1',
        agentTaskId: 'follow-up-1',
        canonicalPath: '/tmp/report.md',
        operation: 'overwrite',
        origin: 'model',
        postImageSizeBytes: 42,
        restoresChangeId: null,
        createdAt: '2026-08-16T00:00:00Z',
        appliedAt: '2026-08-16T00:00:01Z',
      },
    ]);
  });

  it('requests version content through the initialized shared client with an encoded change id', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      change_id: 'change/1',
      canonical_path: '/tmp/report.md',
      content: '# Report\n',
      truncated: false,
      byte_size: 10,
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const content = await getManagedFileVersionContent('change/1');

    const requestedUrl = fetchMock.mock.calls[0][0] as string;
    expect(requestedUrl).toBe(
      'http://localhost:8000/api/v1/agent-tasks/managed-file-history/versions/change%2F1/content',
    );
    expect(content).toEqual({
      changeId: 'change/1',
      canonicalPath: '/tmp/report.md',
      content: '# Report\n',
      truncated: false,
      byteSize: 10,
    });
  });

  it('posts restore through the initialized shared client and maps a successful response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      change_id: 'change-3',
      canonical_path: '/tmp/report.md',
      restored_from_change_id: 'change-1',
    }));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await restoreManagedFileVersion({
      rootTaskId: 'root-1',
      canonicalPath: '/tmp/report.md',
      restoresChangeId: 'change-1',
      agentTaskId: 'follow-up-1',
    });

    expect(fetchMock.mock.calls[0][0]).toBe('http://localhost:8000/api/v1/agent-tasks/managed-file-history/restore');
    const [, requestInit] = fetchMock.mock.calls[0];
    expect(JSON.parse((requestInit as RequestInit).body as string)).toEqual({
      root_task_id: 'root-1',
      canonical_path: '/tmp/report.md',
      restores_change_id: 'change-1',
      agent_task_id: 'follow-up-1',
    });
    expect(result).toEqual({
      success: true,
      changeId: 'change-3',
      canonicalPath: '/tmp/report.md',
      restoredFromChangeId: 'change-1',
    });
  });

  it('maps a backend restore-conflict error into the non-destructive workspace error state', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      detail: { error: 'The file was modified outside managed history; refusing to restore.' },
    }, 409));
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const result = await restoreManagedFileVersion({
      rootTaskId: 'root-1',
      canonicalPath: '/tmp/report.md',
      restoresChangeId: 'change-1',
    });

    expect(result.success).toBe(false);
    expect(result.error).toContain('refusing to restore');
  });
});
