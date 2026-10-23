import { describe, expect, it } from 'vitest';
import { parseResourceAdviceState, parseThermalState } from './resourceAdviceTypes';

const good = { id: 'transcription_lag', severity: 'warning', title: 'Transcription is behind the meeting', detail: 'Choose a smaller model.', action: 'open_settings', raised_at: 1700000000.5 };

describe('parseThermalState', () => {
  it('accepts the four macOS names and rejects everything else', () => {
    for (const name of ['nominal', 'fair', 'serious', 'critical']) expect(parseThermalState(name)).toBe(name);
    for (const value of ['hot', '', null, undefined, 3, {}, 'Serious']) expect(parseThermalState(value)).toBeNull();
  });
});

describe('parseResourceAdviceState', () => {
  it('reads a well-formed state', () => {
    expect(parseResourceAdviceState({ revision: 3, advice: [good] })).toEqual({ revision: 3, advice: [good] });
  });

  it('ignores extra fields such as the websocket event type', () => {
    expect(parseResourceAdviceState({ event_type: 'resource_advice', revision: 1, advice: [], extra: true })).toEqual({ revision: 1, advice: [] });
  });

  it('rejects payloads that are not a state', () => {
    for (const value of [null, undefined, 'x', 4, [], { advice: [] }, { revision: 'a', advice: [] }, { revision: -1, advice: [] }, { revision: 1.5, advice: [] }, { revision: 1 }, { revision: 1, advice: 'no' }]) {
      expect(parseResourceAdviceState(value)).toBeNull();
    }
  });

  it('drops malformed items and keeps the good ones', () => {
    const state = parseResourceAdviceState({
      revision: 2,
      advice: [
        good,
        null,
        'text',
        { ...good, id: '' },
        { ...good, severity: 'fatal' },
        { ...good, action: 'delete_everything' },
        { ...good, title: 4 },
        { ...good, detail: undefined },
        { ...good, raised_at: 'soon' },
        { ...good, raised_at: Number.NaN },
      ],
    });
    expect(state).toEqual({ revision: 2, advice: [good] });
  });
});
