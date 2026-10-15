import { describe, expect, it } from 'vitest';
import { cloudState } from './cloudTestFixtures';
import { chipLabel, chipTone, fallbackNotice, providerLabel } from './cloudTranscriptionPresentation';

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
