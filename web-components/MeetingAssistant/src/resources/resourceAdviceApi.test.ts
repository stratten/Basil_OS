import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { dismissResourceAdvice, fetchResourceAdvice, reportThermalState, resourceAdviceSocketUrl } from './resourceAdviceApi';

const state = { revision: 4, advice: [{ id: 'thermal', severity: 'warning', title: 'Your Mac is running hot', detail: 'detail', action: 'none', raised_at: 5 }] };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify(state), { status: 200 })));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('resource advice API', () => {
  it('reads the current advice from the loopback backend', async () => {
    await expect(fetchResourceAdvice(8123)).resolves.toEqual(state);
    expect(fetchMock).toHaveBeenCalledWith('http://127.0.0.1:8123/meetings/resource-advice', expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }));
  });

  it('reports the thermal state with a PUT body the backend accepts', async () => {
    await reportThermalState(8123, 'critical');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:8123/meetings/resource-advice/client-state');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({ thermal_state: 'critical' });
  });

  it('encodes the advice id in the dismissal path', async () => {
    await dismissResourceAdvice(8123, 'a/b c?');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:8123/meetings/resource-advice/a%2Fb%20c%3F/dismiss');
    expect(init.method).toBe('POST');
  });

  it('throws on an error status and on a response that is not an advice state', async () => {
    fetchMock.mockImplementationOnce(() => Promise.resolve(new Response('{}', { status: 503 })));
    await expect(fetchResourceAdvice(8123)).rejects.toThrow('(503)');
    fetchMock.mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({ revision: 'x' }), { status: 200 })));
    await expect(fetchResourceAdvice(8123)).rejects.toThrow('not understood');
  });

  it('uses the shared backend socket', () => {
    expect(resourceAdviceSocketUrl(8123)).toBe('ws://127.0.0.1:8123/ws');
  });
});
