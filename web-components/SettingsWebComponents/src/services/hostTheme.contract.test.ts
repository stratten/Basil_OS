// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { applyHostTheme } from './hostTheme';
import type { FontPayload, ThemePayload } from '../types';
import {
  CONTRACT_FONT_FIXTURE,
  CONTRACT_THEME_FIXTURE,
  SETTINGS_THEME_TOKENS,
  assertAppliesThemeTokens,
} from '@shared/webThemeContractSuite';

describe('Settings host theme contract', () => {
  it('applies every verbatim-echoed field of its own 15-field ThemePayload plus the shared font contract', () => {
    assertAppliesThemeTokens(
      (theme) => applyHostTheme(theme as ThemePayload, CONTRACT_FONT_FIXTURE as FontPayload),
      SETTINGS_THEME_TOKENS,
    );

    const style = document.documentElement.style;
    expect(style.getPropertyValue('--font-family')).toBe(CONTRACT_FONT_FIXTURE.fontFamily);
    expect(style.getPropertyValue('--font-family-medium')).toBe(CONTRACT_FONT_FIXTURE.fontFamilyMedium);
    expect(style.getPropertyValue('--font-family-bold')).toBe(CONTRACT_FONT_FIXTURE.fontFamilyBold);
  });

  it('publishes textPrimary/separatorColor/fieldBorder as --host-* inputs instead of echoing them verbatim', () => {
    applyHostTheme(CONTRACT_THEME_FIXTURE as ThemePayload, CONTRACT_FONT_FIXTURE as FontPayload);
    const style = document.documentElement.style;
    // These three are excluded from SETTINGS_THEME_TOKENS (see its doc comment) because
    // appearance-settings.css's palette-aware wireframe-tint :root rule derives the real
    // --text-primary/--separator-color/--field-border from these --host-* inputs via
    // color-mix(), instead of this function echoing the palette value to those names
    // directly. Asserting the --host-* names here proves the raw palette value still
    // reaches the derivation; asserting the canonical names are unset here proves this
    // function no longer sets them directly (which would silently re-introduce the
    // !important collision the wireframe-tint rule was rewritten to avoid).
    expect(style.getPropertyValue('--host-text-primary')).toBe(CONTRACT_THEME_FIXTURE.textPrimary);
    expect(style.getPropertyValue('--host-separator-color')).toBe(CONTRACT_THEME_FIXTURE.separatorColor);
    expect(style.getPropertyValue('--host-field-border')).toBe(CONTRACT_THEME_FIXTURE.fieldBorder);
    expect(style.getPropertyValue('--text-primary')).toBe('');
    expect(style.getPropertyValue('--separator-color')).toBe('');
    expect(style.getPropertyValue('--field-border')).toBe('');
  });

  it('does not regress the 4-field gap into a 5th missing field', () => {
    applyHostTheme(CONTRACT_THEME_FIXTURE as ThemePayload, CONTRACT_FONT_FIXTURE as FontPayload);
    const style = document.documentElement.style;
    // These four remain unset by Settings' own bespoke ThemePayload today (accepted debt from
    // Package 4; see SETTINGS_THEME_TOKENS' doc comment). If this assertion starts failing because
    // Settings' native sender now emits these fields, that is progress: update `types.ts`'s
    // `ThemePayload` to include them, wire `hostTheme.ts` to apply them, and widen this test (and
    // `SETTINGS_THEME_TOKENS`) to the full 19-token contract instead of leaving this test red.
    expect(style.getPropertyValue('--success-base')).toBe('');
    expect(style.getPropertyValue('--error-base')).toBe('');
    expect(style.getPropertyValue('--ready-base')).toBe('');
    expect(style.getPropertyValue('--ready-accent')).toBe('');
  });

  it('applies the surface finish through the shared injector', () => {
    applyHostTheme(
      { ...CONTRACT_THEME_FIXTURE, surfaceFinish: 'metal' } as ThemePayload,
      CONTRACT_FONT_FIXTURE as FontPayload,
    );

    expect(document.documentElement.dataset.surfaceFinish).toBe('metal');
  });
});
