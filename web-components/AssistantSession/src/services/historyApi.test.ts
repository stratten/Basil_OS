import { describe, expect, it } from 'vitest';
import { materialRefinements } from './historyApi';

describe('materialRefinements', () => {
  it('drops placeholder entries without a persisted instruction and output', () => {
    expect(materialRefinements([
      { instruction: '', output: '', timestamp: '2026-09-23T00:00:00Z' },
      { instruction: 'Make it shorter', output: 'Shorter output', timestamp: '2026-09-23T00:01:00Z' },
    ])).toEqual([
      { instruction: 'Make it shorter', output: 'Shorter output', timestamp: '2026-09-23T00:01:00Z' },
    ]);
  });

  it('keeps an empty history empty', () => {
    expect(materialRefinements([])).toEqual([]);
  });
});
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fetchHistory, saveWritingSample } from './historyApi';

describe('historyApi', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('preserves the 50-row cap and modality filter on list requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ outputs: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await fetchHistory('http://localhost:8000', { inputModality: 'voice' });

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/assistant-outputs?limit=50&input_modality=voice',
      expect.objectContaining({ headers: expect.any(Object) }),
    );
  });

  it('uses the search endpoint only for nonempty trimmed queries', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ outputs: [] }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await fetchHistory('http://localhost:8000', { query: '  status report  ' });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://localhost:8000/assistant-outputs/search?limit=50&q=status+report',
    );
  });

  it('sends edited history content to the canonical writing-sample endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'saved' }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await saveWritingSample('http://localhost:8000', 'Edited output', 'Mail');

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/user/writing-samples',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ content: 'Edited output', metadata: { app_name: 'Mail' } }),
      }),
    );
  });
});
