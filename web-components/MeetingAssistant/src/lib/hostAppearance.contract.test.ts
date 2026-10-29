// @vitest-environment jsdom
import { describe, it } from 'vitest';
import { applyMeetingHostFonts, applyMeetingHostTheme } from './hostAppearance';
import {
  FULL_THEME_TOKENS,
  assertAppliesFontTokens,
  assertAppliesThemeTokens,
} from '@shared/webThemeContractSuite';

describe('Meeting Assistant host appearance contract', () => {
  it('forwards the full theme contract to the shared applier', () => {
    assertAppliesThemeTokens((theme) => applyMeetingHostTheme({ ...theme }), FULL_THEME_TOKENS);
  });

  it('forwards the full font contract to the shared applier', () => {
    assertAppliesFontTokens((fonts) => applyMeetingHostFonts({ ...fonts }));
  });

  it('tolerates a null theme/fonts payload without throwing', () => {
    applyMeetingHostTheme(null);
    applyMeetingHostFonts(null);
  });
});
