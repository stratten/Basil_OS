import { describe, expect, it } from 'vitest';
import { shouldAutoCollapseThinking } from './thinkingPresentation';

describe('thinking presentation', () => {
  it('collapses at the first visible response token', () => {
    expect(shouldAutoCollapseThinking(false, true, false)).toBe(true);
  });

  it('collapses when mounted after response streaming has already started', () => {
    expect(shouldAutoCollapseThinking(true, true, false)).toBe(true);
  });

  it('does not repeatedly collapse later response chunks', () => {
    expect(shouldAutoCollapseThinking(true, true, true)).toBe(false);
  });

  it('does not collapse before user-facing response streaming', () => {
    expect(shouldAutoCollapseThinking(false, false, false)).toBe(false);
  });

  it('allows a new reasoning segment to reset one-shot handling', () => {
    expect(shouldAutoCollapseThinking(false, true, false)).toBe(true);
  });
});
