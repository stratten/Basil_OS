import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EMPTY_COMPANION_STATUS, type CompanionSnapshot, type CompanionSocketEvent } from './types';

const { sockets, FakeSocket } = vi.hoisted(() => {
  const created: Array<{ handlers: Array<(frame: CompanionSocketEvent) => void> }> = [];

  class HoistedFakeSocket {
    handlers: Array<(frame: CompanionSocketEvent) => void> = [];
    constructor() {
      created.push(this);
    }
    subscribe(handler: (frame: CompanionSocketEvent) => void) {
      this.handlers.push(handler);
      return () => undefined;
    }
    onConnect() {
      return () => undefined;
    }
    connect() {}
    disconnect() {}
  }

  return { sockets: created, FakeSocket: HoistedFakeSocket };
});

vi.mock('@shared/websocket/reconnectingWebSocket', () => ({ ReconnectingWebSocket: FakeSocket }));

import { useCompanion } from './useCompanion';

const proposal = {
  id: 'p1',
  kind: 'proposal',
  text: 'Add a reminder',
  confidence: 0.9,
  citations: [],
  no_source: false,
  transcript_range: { start: 1, end: 3, turn_ids: [] },
  trigger: 'investigation',
  watch_id: null,
  truncated: false,
  pinned: false,
  dismissed: false,
  proposal: {
    proposal_id: 'pr-1',
    action: 'todo',
    title: 'Add a reminder',
    instruction: 'Remind me.',
    authority: 'review',
    state: 'proposed',
    todo_id: null,
    agent_task_id: null,
    error: null,
    auto_started: false,
  },
};

function snapshot(overrides: Partial<CompanionSnapshot> = {}): CompanionSnapshot {
  return {
    meeting_id: 'm1',
    session_key: 's1',
    status: { ...EMPTY_COMPANION_STATUS, live: true, enabled: true },
    roots: [],
    items: [proposal] as unknown as CompanionSnapshot['items'],
    watches: [],
    chat: [],
    retrievals: [],
    last_seq: 0,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('useCompanion proposals and investigations', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    sockets.length = 0;
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  async function ready(extra: (url: string, init?: RequestInit) => Response | null) {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => Promise.resolve(extra(url, init) ?? jsonResponse(snapshot())));
    const hook = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(hook.result.current.state.phase).toBe('ready'));
    return hook;
  }

  it('posts the decision and records the answer on the card', async () => {
    const { result } = await ready((url, init) =>
      url.endsWith('/items/p1/proposal') && init?.method === 'POST'
        ? jsonResponse({ state: 'started', title: 'Add a reminder', instruction: 'Remind me.', todo_id: 't-1', agent_task_id: null, error: null })
        : null,
    );
    let answer: unknown;
    await act(async () => {
      answer = await result.current.decideProposal('p1', 'approve');
    });
    expect(answer).toMatchObject({ state: 'started', todo_id: 't-1' });
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/items/p1/proposal'));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ decision: 'approve' });
    expect(result.current.state.timeline.items[0].proposal).toMatchObject({ state: 'started', todo_id: 't-1' });
  });

  it('shows the backend detail and reloads when the decision request fails', async () => {
    const { result } = await ready((url, init) =>
      url.endsWith('/items/p1/proposal') && init?.method === 'POST' ? jsonResponse({ detail: 'That proposal was already decided.' }, 409) : null,
    );
    const before = fetchMock.mock.calls.length;
    let answer: unknown = 'unset';
    await act(async () => {
      answer = await result.current.decideProposal('p1', 'approve');
    });
    expect(answer).toBeNull();
    expect(result.current.actionError).toContain('already decided');
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before + 1));
  });

  it('starts an investigation with the question', async () => {
    const { result } = await ready((url, init) =>
      url.endsWith('/investigations') && init?.method === 'POST' ? jsonResponse({ investigation_id: 'inv-1' }, 202) : null,
    );
    let started = false;
    await act(async () => {
      started = await result.current.investigate('When does the contract renew?');
    });
    expect(started).toBe(true);
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/investigations'));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ question: 'When does the contract renew?' });
  });

  it('shows the refusal when an investigation is not allowed', async () => {
    const { result } = await ready((url, init) =>
      url.endsWith('/investigations') && init?.method === 'POST' ? jsonResponse({ detail: 'Research is turned off for this meeting.' }, 409) : null,
    );
    let started = true;
    await act(async () => {
      started = await result.current.investigate('Anything');
    });
    expect(started).toBe(false);
    expect(result.current.actionError).toContain('Research is turned off');
  });

  it('cancels each unresolved investigation and treats an already finished one as stopped', async () => {
    const withRuns = snapshot({
      items: [],
      retrievals: [
        { id: 'r1', seq: 1, kind: 'retrieval', meeting_time: 1, wall_time: '', payload: { purpose: 'investigation', investigation_id: 'inv-1', queries: ['one'] } },
        { id: 'r2', seq: 2, kind: 'retrieval', meeting_time: 2, wall_time: '', payload: { purpose: 'investigation', investigation_id: 'inv-2', queries: ['two'] } },
      ] as unknown as CompanionSnapshot['retrievals'],
      last_seq: 2,
    });
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === 'DELETE' && url.endsWith('/investigations/inv-1')) return Promise.resolve(jsonResponse({ detail: 'Not found.' }, 404));
      if (init?.method === 'DELETE') return Promise.resolve(jsonResponse({ ok: true }));
      return Promise.resolve(jsonResponse(withRuns));
    });
    const { result } = renderHook(() => useCompanion({ meetingId: 'm1', port: 8123, selectedModelId: null }));
    await waitFor(() => expect(result.current.state.phase).toBe('ready'));
    let stopped = false;
    await act(async () => {
      stopped = await result.current.stopInvestigations();
    });
    expect(stopped).toBe(true);
    const deletes = fetchMock.mock.calls.filter(([, init]) => init?.method === 'DELETE').map(([url]) => String(url));
    expect(deletes).toEqual([expect.stringContaining('/investigations/inv-1'), expect.stringContaining('/investigations/inv-2')]);
    expect(result.current.actionError).toBeNull();
  });

  it('patches the per-meeting research switch and applies the returned status', async () => {
    const { result } = await ready((_url, init) => {
      if (init?.method === 'PATCH') return jsonResponse({ ...EMPTY_COMPANION_STATUS, live: true, enabled: true, investigate: false });
      return null;
    });
    await act(async () => {
      await result.current.setInvestigate(false);
    });
    const call = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH');
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ investigate: false });
    expect(result.current.state.status.investigate).toBe(false);
  });
});
