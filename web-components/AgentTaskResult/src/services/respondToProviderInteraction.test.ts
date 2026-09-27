import { afterEach, describe, expect, it, vi } from 'vitest';
import { respondToProviderInteraction, setBaseUrl } from './api';

describe('respondToProviderInteraction', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('posts the outcome and values to the provider-interactions respond endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      message: 'Provider interaction answer delivered.',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8000);

    await expect(
      respondToProviderInteraction('task-1', 'interaction-1', 'accept', { strategy: 'balanced' })
    ).resolves.toEqual({
      success: true,
      message: 'Provider interaction answer delivered.',
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ outcome: 'accept', values: { strategy: 'balanced' } }),
      }),
    );
  });

  it('omits values when cancelling without a values argument', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      success: true,
      message: 'Provider interaction answer delivered.',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    setBaseUrl(8000);

    await respondToProviderInteraction('task-1', 'interaction-1', 'cancel');

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/api/v1/agent-tasks/task-1/provider-interactions/interaction-1/respond',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ outcome: 'cancel' }),
      }),
    );
  });
});
