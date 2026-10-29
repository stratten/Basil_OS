// @vitest-environment jsdom
import { describe, it } from 'vitest';
import { applyHostFonts, applyHostTheme } from './agentTaskTheme';
import { FULL_THEME_TOKENS, assertAppliesFontTokens, assertAppliesThemeTokens } from '@shared/webThemeContractSuite';

describe('Basil Board theme contract', () => {
  it('applies the full theme contract', () => {
    assertAppliesThemeTokens(applyHostTheme, FULL_THEME_TOKENS);
  });

  it('applies the full font contract', () => {
    assertAppliesFontTokens(applyHostFonts);
  });
});
