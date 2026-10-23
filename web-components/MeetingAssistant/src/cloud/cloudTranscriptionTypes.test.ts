import { describe, expect, it } from 'vitest';
import { cloudState } from './cloudTestFixtures';
import { parseCloudCheckResult, parseCloudStatus, parseCloudTranscriptionState } from './cloudTranscriptionTypes';

describe('parseCloudTranscriptionState', () => {
  it('accepts a well-formed state', () => {
    expect(parseCloudTranscriptionState(cloudState({ enabled: true }))).toEqual(cloudState({ enabled: true }));
  });

  it.each([
    ['not an object', null],
    ['an unknown provider', { ...cloudState(), provider: 'other' }],
    ['an unknown connection', { ...cloudState(), connection: 'other' }],
    ['a non-boolean enabled', { ...cloudState(), enabled: 'yes' }],
    ['missing providers', { ...cloudState(), providers: undefined }],
    ['only malformed providers', { ...cloudState(), providers: [{ id: 'x' }] }],
    ['a missing status', { ...cloudState(), status: undefined }],
    ['an unknown status state', { ...cloudState(), status: { state: 'maybe' } }],
  ])('rejects %s', (_label, value) => {
    expect(parseCloudTranscriptionState(value)).toBeNull();
  });

  it('drops malformed providers but keeps the valid ones', () => {
    const parsed = parseCloudTranscriptionState({ ...cloudState(), providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'nope' }] });
    expect(parsed?.providers).toEqual([{ id: 'deepgram', label: 'Deepgram', has_key: true }]);
  });
});

describe('parseCloudStatus', () => {
  it('reads a socket frame and ignores its event type', () => {
    expect(parseCloudStatus({ event_type: 'cloud_transcription_status', state: 'streaming', provider: 'deepgram', tier: 'streaming', reason: null })).toEqual({
      state: 'streaming',
      provider: 'deepgram',
      tier: 'streaming',
      reason: null,
    });
  });

  it('turns missing optional fields into null and rejects an unknown state', () => {
    expect(parseCloudStatus({ state: 'off' })).toEqual({ state: 'off', provider: null, tier: null, reason: null });
    expect(parseCloudStatus({ state: 'paused' })).toBeNull();
    expect(parseCloudStatus('streaming')).toBeNull();
  });
});

describe('parseCloudCheckResult', () => {
  it('requires a boolean and a message', () => {
    expect(parseCloudCheckResult({ ok: true, message: 'Connected.' })).toEqual({ ok: true, message: 'Connected.' });
    expect(parseCloudCheckResult({ ok: 'true', message: 'x' })).toBeNull();
    expect(parseCloudCheckResult({ ok: true })).toBeNull();
    expect(parseCloudCheckResult(undefined)).toBeNull();
  });
});
