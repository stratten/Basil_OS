// web-components/AssistantSession/src/state/assistantSessionReducer.test.ts

import { describe, expect, it } from 'vitest';
import { applyAssistantSessionEvent, initialAssistantSessionState } from './assistantSessionReducer';
import { PROTOCOL_VERSION } from '../bridge/types';

const {
  revision: _revision,
  hasSnapshot: _hasSnapshot,
  theme: _theme,
  ...basePayload
} = initialAssistantSessionState;

describe('assistantSessionReducer', () => {
  it('applies a snapshot unconditionally and seeds revision', () => {
    const next = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'snapshot',
      revision: 5,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
      assistantOutput: 'hello',
      typedInstruction: 'preserve this draft',
    });
    expect(next.revision).toBe(5);
    expect(next.assistantOutput).toBe('hello');
    expect(next.typedInstruction).toBe('preserve this draft');
    expect(next.hasSnapshot).toBe(true);
  });

  it('applies a delta whose revision is strictly greater than the current revision', () => {
    const seeded = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'snapshot',
      revision: 1,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
    });
    const next = applyAssistantSessionEvent(seeded, {
      type: 'delta',
      revision: 2,
      protocolVersion: PROTOCOL_VERSION,
      assistantOutput: 'partial',
    });
    expect(next.revision).toBe(2);
    expect(next.assistantOutput).toBe('partial');
  });

  it('drops a delta whose revision is not strictly greater than the applied revision', () => {
    const seeded = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'snapshot',
      revision: 4,
      protocolVersion: PROTOCOL_VERSION,
      ...basePayload,
      assistantOutput: 'keep-me',
    });
    const next = applyAssistantSessionEvent(seeded, {
      type: 'delta',
      revision: 4,
      protocolVersion: PROTOCOL_VERSION,
      assistantOutput: 'stale',
    });
    expect(next.revision).toBe(4);
    expect(next.assistantOutput).toBe('keep-me');
  });

  it('rejects a snapshot from an unsupported protocol version and leaves state untouched', () => {
    const next = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'snapshot',
      revision: 1,
      protocolVersion: PROTOCOL_VERSION + 1,
      ...basePayload,
      assistantOutput: 'should-not-apply',
    });
    expect(next).toBe(initialAssistantSessionState);
  });

  it('ignores meter events entirely', () => {
    const next = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'meter',
      audioLevel: 0.42,
    });
    expect(next).toBe(initialAssistantSessionState);
  });

  it('applies init events by seeding the theme without touching revision', () => {
    const theme = {
      primary: '#000000',
      secondary: '#111111',
      backgroundPrimary: '#FFFFFF',
      backgroundSecondary: '#EEEEEE',
      textPrimary: '#000000',
      textSecondary: '#333333',
      textTertiary: '#666666',
      recordingBase: '#8B0000',
      recordingAccent: '#C23B3B',
      readyBase: '#2F6FED',
      readyAccent: '#8FB2F7',
      processingBase: '#7C3AED',
      processingAccent: '#DDD6FE',
      successBase: '#1E8E5A',
      errorBase: '#D33B3B',
      preferredFontName: 'Inter',
    };
    const next = applyAssistantSessionEvent(initialAssistantSessionState, {
      type: 'init',
      protocolVersion: PROTOCOL_VERSION,
      theme,
    });
    expect(next.theme).toEqual(theme);
    expect(next.revision).toBe(0);
  });
});
