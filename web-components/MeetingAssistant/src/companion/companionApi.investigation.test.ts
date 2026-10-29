import { afterEach, describe, expect, it, vi } from 'vitest';
import { startCompanionInvestigation } from './companionApi';

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ investigation_id: 'iv-1' }), { status: 202, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('startCompanionInvestigation', () => {
  it('sends only the question when no chat message is named', async () => {
    const fetchMock = stubFetch();
    await startCompanionInvestigation(8000, 'm1', 'What is the renewal term?');
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('http://127.0.0.1:8000/meetings/m1/companion/investigations');
    expect(JSON.parse(String(init.body))).toEqual({ question: 'What is the renewal term?' });
  });

  it('names the chat message the question came from', async () => {
    const fetchMock = stubFetch();
    await startCompanionInvestigation(8000, 'm1', 'What is the renewal term?', 'm-77');
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({ question: 'What is the renewal term?', reply_to_message_id: 'm-77' });
  });
});
