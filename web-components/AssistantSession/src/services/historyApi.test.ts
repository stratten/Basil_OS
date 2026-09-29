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
import { fetchHistory, fetchHistoryDetail, saveHistoryOutputAsSample, updateSavedSampleContent } from './historyApi';

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

  it('saves history output through the linked save-sample endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'saved', sample_id: 'sample-9', content: 'Edited output' }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const sample = await saveHistoryOutputAsSample('http://localhost:8000', 7, 'Edited output', 'document');

    expect(sample).toEqual({ id: 'sample-9', content: 'Edited output' });
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/assistant-outputs/7/save-sample',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ content: 'Edited output', context_type: 'document' }),
      }),
    );
  });

  it('updates a linked writing sample with a content-only PATCH', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'updated', sample_id: 'sample 3', content: 'New text' }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await updateSavedSampleContent('http://localhost:8000', 'sample 3', 'New text');

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/user/writing-samples/sample%203',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ content: 'New text' }) }),
    );
  });

  it('maps saved-sample state from a history detail payload', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 7,
      output_type: 'assistant_session',
      input_modality: null,
      output_text: 'Original reply',
      context_text: null,
      explanation_text: null,
      model_name: null,
      timestamp: '2026-09-28T13:54:00Z',
      status: 'completed',
      refinement_count: 0,
      refinements: [],
      app_name: 'Mail',
      user_request: null,
      processing_time_ms: null,
      sample_context_type: 'email_reply',
      recipient: 'miriam@example.com',
      saved_sample: { id: 'sample-3', content: 'Original reply', context_type: 'email_reply' },
    }), { status: 200 })));

    const detail = await fetchHistoryDetail('http://localhost:8000', 7);

    expect(detail.sampleContextType).toBe('email_reply');
    expect(detail.recipient).toBe('miriam@example.com');
    expect(detail.savedSample).toEqual({ id: 'sample-3', content: 'Original reply' });
  });

  it('omits context_type when the row already has a stored context', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'saved', sample_id: 'sample-9', content: 'Output' }), { status: 200 }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await saveHistoryOutputAsSample('http://localhost:8000', 7, 'Output', null);

    expect(fetchMock.mock.calls[0]?.[1]).toEqual(expect.objectContaining({ body: JSON.stringify({ content: 'Output' }) }));
  });

  it('rejects with the HTTP status when the save is refused', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Choose a writing context.', { status: 400 })));

    await expect(saveHistoryOutputAsSample('http://localhost:8000', 7, 'Output', null)).rejects.toMatchObject({ status: 400 });
  });

  it('maps legacy and missing sample fields to null', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 8,
      output_type: 'suggestion',
      input_modality: null,
      output_text: 'Old output',
      context_text: null,
      explanation_text: null,
      model_name: null,
      timestamp: '2026-01-01T00:00:00Z',
      status: 'completed',
      refinement_count: 0,
      refinements: [],
      app_name: null,
      user_request: null,
      processing_time_ms: null,
      sample_context_type: 'slack',
    }), { status: 200 })));

    const detail = await fetchHistoryDetail('http://localhost:8000', 8);

    expect(detail.sampleContextType).toBeNull();
    expect(detail.recipient).toBeNull();
    expect(detail.savedSample).toBeNull();
  });
});
