import { describe, expect, it } from 'vitest';
import {
  appearanceTokenContract,
  contrastRatio,
  meetsMinimumContrast,
} from './appearanceTokenContract';

describe('appearanceTokenContract', () => {
  it('exposes every derived and fixed token name', () => {
    expect(appearanceTokenContract.derivedSurfaceTokens).toEqual([
      'surfaceRaised', 'surfaceSunken', 'surfaceOverlay', 'surfaceSelected', 'surfaceHover', 'surfaceDisabled',
    ]);
    expect(appearanceTokenContract.derivedTextTokens).toEqual([
      'textSecondary', 'textTertiary', 'textOnPrimary', 'textOnSuccess', 'textOnWarning', 'textOnError',
    ]);
    expect(appearanceTokenContract.derivedStructuralTokens).toEqual([
      'separator', 'fieldBorder', 'focusRing', 'shadow',
    ]);
    expect(appearanceTokenContract.fixedSemanticStateTokens).toEqual([
      'recordingBase', 'recordingAccent', 'successBase', 'warningBase', 'errorBase', 'processingBase', 'processingAccent', 'readyBase', 'readyAccent',
    ]);
  });

  it('computes WCAG relative-luminance contrast ratio', () => {
    expect(contrastRatio([0, 0, 0], [1, 1, 1])).toBeCloseTo(21, 3);
    expect(contrastRatio([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])).toBeCloseTo(1, 3);
  });

  it('distinguishes normal-text and large-text minimum contrast', () => {
    const foreground: readonly [number, number, number] = [0.5, 0.5, 0.5];
    const background: readonly [number, number, number] = [1, 1, 1];

    expect(meetsMinimumContrast(foreground, background, false)).toBe(false);
    expect(meetsMinimumContrast(foreground, background, true)).toBe(true);
  });

  it('rejects malformed or out-of-range RGB components', () => {
    expect(() => contrastRatio([-0.1, 0, 0], [1, 1, 1])).toThrow(RangeError);
    expect(() => contrastRatio([1.1, 0, 0], [1, 1, 1])).toThrow(RangeError);
    expect(() => contrastRatio([Number.NaN, 0, 0], [1, 1, 1])).toThrow(RangeError);
  });
});
