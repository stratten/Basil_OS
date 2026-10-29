// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { applyTranscriptionTheme } from './themeCssVars';
import type { TranscriptionThemePayload } from '../bridge/types';
import {
  CONTRACT_FONT_FIXTURE,
  CONTRACT_THEME_FIXTURE,
  FULL_THEME_TOKENS,
  assertAppliesThemeTokens,
} from '@shared/webThemeContractSuite';

const NON_DERIVED_TOKENS = FULL_THEME_TOKENS.filter((token) => token !== 'separatorColor');

describe('Transcription Widget theme contract', () => {
  it('applies every non-derived theme token verbatim', () => {
    assertAppliesThemeTokens(
      (theme) => applyTranscriptionTheme({ ...theme, preferredFontName: CONTRACT_FONT_FIXTURE.fontFamily } as TranscriptionThemePayload),
      NON_DERIVED_TOKENS,
    );
  });

  it('derives separatorColor from secondary via color-mix instead of echoing the fixture value', () => {
    applyTranscriptionTheme({
      ...CONTRACT_THEME_FIXTURE,
      preferredFontName: CONTRACT_FONT_FIXTURE.fontFamily,
    } as TranscriptionThemePayload);
    const separator = document.documentElement.style.getPropertyValue('--separator-color');
    expect(separator).toBe(`color-mix(in srgb, ${CONTRACT_THEME_FIXTURE.secondary} 18%, transparent)`);
    expect(separator).not.toBe(CONTRACT_THEME_FIXTURE.separatorColor);
  });

  it('maps preferredFontName onto all three font custom properties', () => {
    applyTranscriptionTheme({
      ...CONTRACT_THEME_FIXTURE,
      preferredFontName: 'Basil-Contract-Single',
    } as TranscriptionThemePayload);
    const style = document.documentElement.style;
    expect(style.getPropertyValue('--font-family')).toBe('Basil-Contract-Single');
    expect(style.getPropertyValue('--font-family-medium')).toBe('Basil-Contract-Single');
    expect(style.getPropertyValue('--font-family-bold')).toBe('Basil-Contract-Single');
  });
});
