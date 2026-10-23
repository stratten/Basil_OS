import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cloudState, jsonResponse } from './cloudTestFixtures';
import {
  CloudApiError,
  checkCloudProvider,
  cloudTranscriptionSocketUrl,
  deleteCloudKey,
  fetchCloudTranscription,
  saveCloudKey,
  updateCloudSettings,
} from './cloudTranscriptionApi';

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn(() => jsonResponse(cloudState()));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('cloud transcription api', () => {
  it('reads the state from the backend port', async () => {
    expect(await fetchCloudTranscription(8123)).toEqual(cloudState());
    expect(fetchMock.mock.calls[0][0]).toBe('http://127.0.0.1:8123/meetings/cloud-transcription');
  });

  it('sends settings, keys and deletions to the matching routes', async () => {
    await updateCloudSettings(8123, { enabled: true, acknowledge_disclosure: true });
    await saveCloudKey(8123, 'assemblyai', 'aai-key-123456');
    await deleteCloudKey(8123, 'deepgram');
    const calls = fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method, (init as RequestInit).body]);
    expect(calls).toEqual([
      ['http://127.0.0.1:8123/meetings/cloud-transcription/settings', 'PUT', JSON.stringify({ enabled: true, acknowledge_disclosure: true })],
      ['http://127.0.0.1:8123/meetings/cloud-transcription/keys/assemblyai', 'PUT', JSON.stringify({ api_key: 'aai-key-123456' })],
      ['http://127.0.0.1:8123/meetings/cloud-transcription/keys/deepgram', 'DELETE', undefined],
    ]);
  });

  it('runs the connection check and parses its result', async () => {
    fetchMock.mockReturnValueOnce(jsonResponse({ ok: false, message: 'Deepgram rejected the API key.' }));
    expect(await checkCloudProvider(8123, 'deepgram')).toEqual({ ok: false, message: 'Deepgram rejected the API key.' });
    expect((fetchMock.mock.calls[0][1] as RequestInit).body).toBe(JSON.stringify({ provider: 'deepgram' }));
  });

  it('surfaces the backend detail text in a typed error', async () => {
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: 'Add a Deepgram API key first.' }, 409));
    await expect(updateCloudSettings(8123, { enabled: true })).rejects.toMatchObject({ name: 'CloudApiError', status: 409, message: 'Add a Deepgram API key first.' });
    fetchMock.mockReturnValueOnce(jsonResponse({ detail: [{ msg: 'x' }] }, 422));
    await expect(updateCloudSettings(8123, {})).rejects.toBeInstanceOf(CloudApiError);
    fetchMock.mockReturnValueOnce(Promise.resolve(new Response('nope', { status: 500 })));
    await expect(fetchCloudTranscription(8123)).rejects.toMatchObject({ status: 500, message: 'The request failed (500).' });
  });

  it('rejects responses it cannot understand', async () => {
    fetchMock.mockReturnValueOnce(jsonResponse({ unexpected: true }));
    await expect(fetchCloudTranscription(8123)).rejects.toThrow('not understood');
    fetchMock.mockReturnValueOnce(jsonResponse({ unexpected: true }));
    await expect(checkCloudProvider(8123, 'deepgram')).rejects.toThrow('not understood');
  });

  it('uses the shared backend socket', () => {
    expect(cloudTranscriptionSocketUrl(8123)).toBe('ws://127.0.0.1:8123/ws');
  });
});
