import { afterEach, describe, expect, it } from 'vitest';
import { applyHostChainExpansion, getChainExpansionMode } from './chainExpansionPreference';

describe('chainExpansionPreference', () => {
  afterEach(() => applyHostChainExpansion(undefined));

  it('defaults to single', () => {
    expect(getChainExpansionMode()).toBe('single');
  });

  it('adopts multiple and falls back to single for absent or unknown values', () => {
    applyHostChainExpansion('multiple');
    expect(getChainExpansionMode()).toBe('multiple');
    applyHostChainExpansion('all');
    expect(getChainExpansionMode()).toBe('single');
    applyHostChainExpansion('multiple');
    applyHostChainExpansion(undefined);
    expect(getChainExpansionMode()).toBe('single');
  });
});
