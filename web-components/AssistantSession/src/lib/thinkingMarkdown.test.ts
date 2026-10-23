// web-components/AssistantSession/src/lib/thinkingMarkdown.test.ts

import { describe, expect, it } from 'vitest';
import { normalizedThinkingMarkdown } from './thinkingMarkdown';

describe('normalizedThinkingMarkdown', () => {
  it('leaves content with existing paragraph breaks untouched', () => {
    const input = 'First paragraph.\n\nSecond paragraph.';
    expect(normalizedThinkingMarkdown(input)).toBe(input);
  });

  it('promotes single-newline-separated lines to paragraphs', () => {
    const input = 'Line one.\nLine two.\nLine three.';
    expect(normalizedThinkingMarkdown(input)).toBe('Line one.\n\nLine two.\n\nLine three.');
  });

  it('splits a wall of text on sentence boundaries', () => {
    const input = 'First sentence. Second sentence! Third sentence? "Fourth" sentence.';
    expect(normalizedThinkingMarkdown(input)).toBe(
      'First sentence.\n\nSecond sentence!\n\nThird sentence?\n\n"Fourth" sentence.',
    );
  });

  it('handles empty input without throwing', () => {
    expect(normalizedThinkingMarkdown('')).toBe('');
  });
});
