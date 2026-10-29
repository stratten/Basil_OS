import { describe, expect, it } from 'vitest';
import { splitThinking, stripThinking } from './thinkingExtractor';

describe('splitThinking', () => {
  it('returns the raw text when no think tags are present', () => {
    expect(splitThinking('Hello')).toEqual({ thinking: null, content: 'Hello' });
  });

  it('splits a closed think block from the visible content', () => {
    expect(splitThinking('<think>reason</think>\nAnswer')).toEqual({
      thinking: 'reason',
      content: 'Answer',
    });
  });

  it('treats an unterminated think block as all-thinking', () => {
    expect(splitThinking('Intro<think>still going')).toEqual({
      thinking: 'still going',
      content: 'Intro',
    });
  });

  it('strips thinking for callers that only need visible content', () => {
    expect(stripThinking('<think>hidden</think>Visible')).toBe('Visible');
  });
});
