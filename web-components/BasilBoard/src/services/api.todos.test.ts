import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  acceptTodoCandidate,
  addTodoReference,
  cancelTodoItem,
  completeTodoItem,
  configureApiBaseUrl,
  createTodoItem,
  deleteTodoItem,
  dismissTodoCandidate,
  getTodoItem,
  hydrateTodoWorkspace,
  launchTodoWorker,
  listTodoItems,
  promoteMeetingProposalToTodo,
  reopenTodoItem,
  removeTodoReference,
  replaceTodoNotes,
  updateTodoItem,
} from './api';

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  const ok = init.ok ?? true;
  const status = init.status ?? (ok ? 200 : 500);
  return {
    ok, status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe('To-Do API client', () => {
  beforeEach(() => {
    configureApiBaseUrl('http://127.0.0.1:9999');
    vi.stubGlobal('fetch', vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('hydrateTodoWorkspace defaults to newest creation order', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ items: [], next_cursor: null, counts_by_status: {} }),
    );

    const result = await hydrateTodoWorkspace();

    expect(fetch).toHaveBeenCalledWith(
      'http://127.0.0.1:9999/api/v1/todos/workspace?sort_by=created_at&limit=50',
      expect.objectContaining({ headers: expect.objectContaining({ 'Content-Type': 'application/json' }) }),
    );
    expect(result.items).toEqual([]);
  });

  it('hydrateTodoWorkspace includes an explicit sort_direction when provided', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ items: [], next_cursor: null, counts_by_status: {} }),
    );

    await hydrateTodoWorkspace({ column: 'title', direction: 'asc' });

    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      'http://127.0.0.1:9999/api/v1/todos/workspace?sort_by=title&limit=50&sort_direction=asc',
    );
  });

  it('hydrateTodoWorkspace includes title query, status filters, and an opaque cursor', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ items: [], next_cursor: 'next-page', has_more: true, counts_by_status: {} }),
    );

    await hydrateTodoWorkspace(
      { column: 'due_at', direction: 'desc' },
      { query: 'Review 100%_\\', statuses: ['open', 'in_progress'], limit: 20, cursor: 'previous-page' },
    );

    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      'http://127.0.0.1:9999/api/v1/todos/workspace?sort_by=due_at&limit=20&sort_direction=desc&query=Review+100%25_%5C&status=open&status=in_progress&cursor=previous-page',
    );
  });

  it('listTodoItems includes its selected sort and optional status query parameters', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));

    await listTodoItems('open', 'updated_at');
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      'http://127.0.0.1:9999/api/v1/todos/items?sort_by=updated_at&status=open',
    );

    await listTodoItems();
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[1][0]).toBe(
      'http://127.0.0.1:9999/api/v1/todos/items?sort_by=created_at',
    );
  });

  it('getTodoItem URL-encodes the id', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 'a/b' }));
    await getTodoItem('a/b');
    expect((fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe(
      'http://127.0.0.1:9999/api/v1/todos/items/a%2Fb',
    );
  });

  it('createTodoItem POSTs the body as JSON', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    await createTodoItem({ title: 'New item', idempotency_key: 'new-item' });
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ title: 'New item', idempotency_key: 'new-item' });
  });

  it.each([
    ['acceptTodoCandidate', acceptTodoCandidate, 'accept'],
    ['dismissTodoCandidate', dismissTodoCandidate, 'dismiss'],
    ['completeTodoItem', completeTodoItem, 'complete'],
    ['reopenTodoItem', reopenTodoItem, 'reopen'],
    ['cancelTodoItem', cancelTodoItem, 'cancel'],
  ] as const)('%s POSTs expected_revision to /items/{id}/%s', async (_name, fn, segment) => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    await fn('t1', 3);
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe(`http://127.0.0.1:9999/api/v1/todos/items/t1/${segment}`);
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 3 });
  });

  it('launchTodoWorker POSTs only expected_revision and decodes the exact Agent Task id', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ item: { id: 't1', status: 'in_progress' }, agent_task_id: 'worker-123' }),
    );
    const response = await launchTodoWorker('t1', 2);
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/items/t1/workers');
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 2 });
    expect(response.agent_task_id).toBe('worker-123');
    expect(response.item.id).toBe('t1');
  });

  it('updateTodoItem PATCHes arbitrary fields alongside expected_revision', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    await updateTodoItem('t1', { expected_revision: 1, title: 'Renamed' });
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 1, title: 'Renamed' });
  });

  it('deleteTodoItem DELETEs with the expected revision', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    const deleted = await deleteTodoItem('t/1', 4);
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/items/t%2F1');
    expect(init.method).toBe('DELETE');
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 4 });
    expect(deleted).toEqual({ id: 't1' });
  });

  it('updateTodoItem PATCHes a manually edited completed date', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    await updateTodoItem('t1', { expected_revision: 3, completed_at: '2025-12-24T09:30:00Z' });
    const [, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 3, completed_at: '2025-12-24T09:30:00Z' });
  });

  it('replaceTodoNotes PUTs notes and expected_revision', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));
    await replaceTodoNotes('t1', 'New notes', 4);
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/items/t1/notes');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body)).toEqual({ notes: 'New notes', expected_revision: 4 });
  });

  it('addTodoReference POSTs an absolute path and expected revision', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));

    await addTodoReference('t1', '/tmp/brief.pdf', 4);

    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/items/t1/references');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({ path: '/tmp/brief.pdf', expected_revision: 4 });
  });

  it('removeTodoReference DELETEs the reference with the expected revision', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1' }));

    await removeTodoReference('t/1', 'ref/1', 5);

    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/items/t%2F1/references/ref%2F1');
    expect(init.method).toBe('DELETE');
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 5 });
  });

  it('promoteMeetingProposalToTodo POSTs the full proposal payload', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse({ id: 't1', status: 'open' }));
    await promoteMeetingProposalToTodo({
      meeting_id: 'm1', filename: 'f1', proposal_id: 'p1', source_task: 'task',
      suggested_agent_task: 'do it', why_basil_can_help: 'because',
    });
    const [url, init] = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe('http://127.0.0.1:9999/api/v1/todos/meeting-proposals/promote');
    expect(JSON.parse(init.body).proposal_id).toBe('p1');
  });

  it('a 409 conflict response throws with the raw response body as the error message', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(
        { detail: { detail: 'Conflict on To-Do t1', item: { id: 't1', revision: 5 } } },
        { ok: false, status: 409 },
      ),
    );

    await expect(acceptTodoCandidate('t1', 1)).rejects.toThrow(/Conflict on To-Do t1/);
  });

  it('a 422 validation error response throws with the raw response body as the error message', async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ detail: [{ msg: 'title must be between 1 and 240 characters' }] }, { ok: false, status: 422 }),
    );

    await expect(createTodoItem({ title: '', idempotency_key: 'invalid-title' })).rejects.toThrow(/title must be between/);
  });
});
