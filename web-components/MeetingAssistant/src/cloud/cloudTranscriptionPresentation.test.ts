import { describe, expect, it } from 'vitest';
import { cloudState } from './cloudTestFixtures';
import { chipLabel, chipTone, fallbackNotice, liveDefaultValue, liveEngineChoice, liveModelOptions, liveModelValue, providerLabel } from './cloudTranscriptionPresentation';

describe('cloud transcription presentation', () => {
  it('labels the chip for every state', () => {
    expect(chipLabel(null)).toBe('Cloud transcription');
    expect(chipLabel(cloudState())).toBe('Cloud transcription: off');
    expect(chipLabel(cloudState({ enabled: true }))).toBe('Cloud transcription: on');
    expect(chipLabel(cloudState({ enabled: true, status: { state: 'connecting', provider: 'deepgram', tier: 'streaming', reason: null } }))).toBe('Cloud transcription: connecting');
    expect(chipLabel(cloudState({ enabled: true, status: { state: 'streaming', provider: 'assemblyai', tier: 'streaming', reason: null } }))).toBe('Cloud transcription: AssemblyAI');
    expect(chipLabel(cloudState({ enabled: true, status: { state: 'streaming', provider: 'basil_account', tier: 'chunked', reason: null } }))).toBe('Cloud transcription: Basil account');
    expect(chipLabel(cloudState({ enabled: true, status: { state: 'fallback', provider: 'deepgram', tier: 'streaming', reason: 'x' } }))).toBe('Cloud transcription failed, using local');
  });

  it('picks the tone from the live status first and the saved switch second', () => {
    expect(chipTone(null)).toBe('off');
    expect(chipTone(cloudState())).toBe('off');
    expect(chipTone(cloudState({ enabled: true }))).toBe('on');
    expect(chipTone(cloudState({ enabled: false, status: { state: 'streaming', provider: null, tier: null, reason: null } }))).toBe('streaming');
  });

  it('names unknown providers neutrally', () => {
    expect(providerLabel(null)).toBe('cloud');
    expect(providerLabel('mystery')).toBe('cloud');
  });

  it('explains a fallback, with or without a reason, and says nothing otherwise', () => {
    expect(fallbackNotice({ state: 'streaming', provider: null, tier: null, reason: null })).toBeNull();
    expect(fallbackNotice({ state: 'fallback', provider: null, tier: null, reason: 'Deepgram rejected the API key.' })).toBe('Deepgram rejected the API key. The local model is transcribing instead.');
    expect(fallbackNotice({ state: 'fallback', provider: null, tier: null, reason: '  ' })).toBe('Cloud transcription stopped. The local model is transcribing instead.');
  });
});

describe('live transcription model choices', () => {
  const withKeys = (overrides = {}) => cloudState({ acknowledged: true, providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }], ...overrides });

  it('offers only the local model until cloud transcription was acknowledged', () => {
    expect(liveModelOptions(null, 'Whisper Base')).toEqual([{ value: 'local', label: 'Whisper Base', category: 'local' }]);
    expect(liveModelOptions(cloudState({ providers: [{ id: 'deepgram', label: 'Deepgram', has_key: true }, { id: 'assemblyai', label: 'AssemblyAI', has_key: false }] }), 'Whisper Base')).toHaveLength(1);
  });

  it('adds each service with a saved key and the Basil account when it is available', () => {
    expect(liveModelOptions(withKeys(), 'Local').map((option) => option.value)).toEqual(['local', 'deepgram']);
    expect(liveModelOptions(withKeys({ account_available: true }), 'Local').map((option) => option.value)).toEqual(['local', 'deepgram', 'basil_account']);
    expect(liveModelOptions(withKeys(), 'Local')[1].label).toBe('Deepgram');
    expect(liveModelOptions(withKeys(), 'Local').map((option) => option.category)).toEqual(['local', 'api']);
  });

  it('reads the default option from the saved settings', () => {
    const options = liveModelOptions(withKeys({ account_available: true }), 'Local');
    expect(liveDefaultValue(withKeys(), options)).toBe('local');
    expect(liveDefaultValue(withKeys({ enabled: true }), options)).toBe('deepgram');
    expect(liveDefaultValue(withKeys({ enabled: true, connection: 'basil_account' }), options)).toBe('basil_account');
    expect(liveDefaultValue(withKeys({ enabled: true, provider: 'assemblyai' }), options)).toBe('local');
    expect(liveDefaultValue(null, options)).toBe('local');
  });

  it('shows this recording\'s choice when it is available and the saved default otherwise', () => {
    const state = withKeys({ enabled: true });
    const options = liveModelOptions(state, 'Local');
    expect(liveModelValue(state, options)).toBe('deepgram');
    expect(liveModelValue(state, options, null)).toBe('deepgram');
    expect(liveModelValue(state, options, 'local')).toBe('local');
    expect(liveModelValue(withKeys(), options, 'deepgram')).toBe('deepgram');
    expect(liveModelValue(state, options, 'assemblyai')).toBe('deepgram');
    expect(liveModelValue(state, options, 'basil_account')).toBe('deepgram');
  });

  it('sends no choice when the pick matches the saved default and the engine otherwise', () => {
    const state = withKeys({ enabled: true });
    const options = liveModelOptions(state, 'Local');
    expect(liveEngineChoice('deepgram', state, options)).toBeNull();
    expect(liveEngineChoice('local', state, options)).toBe('local');
    const off = withKeys();
    const offOptions = liveModelOptions(off, 'Local');
    expect(liveEngineChoice('local', off, offOptions)).toBeNull();
    expect(liveEngineChoice('deepgram', off, offOptions)).toBe('deepgram');
  });
});
