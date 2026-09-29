import { expect } from 'vitest';
import type { FontConfig, ThemeConfig } from './webTheme';

type ContractThemeTokenKey = Exclude<keyof ThemeConfig, 'surfaceFinish'>;

/**
 * Canonical fixture values every bridge-consumer contract test applies through
 * that consumer's own real theme-apply function. Values are deliberately
 * distinct from any production default so a passing assertion proves the
 * consumer's function actually read and forwarded these exact values, not a
 * coincidental match against a hardcoded fallback.
 */
export const CONTRACT_THEME_FIXTURE: Required<Pick<ThemeConfig, ContractThemeTokenKey>> = {
  backgroundPrimary: '#141414',
  backgroundSecondary: '#1e1e1e',
  backgroundTertiary: '#282828',
  primary: '#3B82F6',
  secondary: '#8B5CF6',
  textPrimary: '#F5F5F5',
  textSecondary: '#B0B0B0',
  textTertiary: '#808080',
  separatorColor: 'rgba(255, 255, 255, 0.12)',
  fieldBorder: 'rgba(255, 255, 255, 0.24)',
  recordingBase: '#EF4444',
  recordingAccent: '#FCA5A5',
  successBase: '#22C55E',
  warningBase: '#F59E0B',
  errorBase: '#DC2626',
  processingBase: '#7C3AED',
  processingAccent: '#DDD6FE',
  readyBase: '#10B981',
  readyAccent: '#A7F3D0',
};

export const CONTRACT_FONT_FIXTURE: Required<FontConfig> = {
  fontFamily: 'Basil-Contract-Regular',
  fontFamilyMedium: 'Basil-Contract-Medium',
  fontFamilyBold: 'Basil-Contract-Bold',
};

const THEME_TOKEN_CSS_VAR: Readonly<Record<ContractThemeTokenKey, string>> = {
  backgroundPrimary: '--background-primary',
  backgroundSecondary: '--background-secondary',
  backgroundTertiary: '--background-tertiary',
  primary: '--primary',
  secondary: '--secondary',
  textPrimary: '--text-primary',
  textSecondary: '--text-secondary',
  textTertiary: '--text-tertiary',
  separatorColor: '--separator-color',
  fieldBorder: '--field-border',
  recordingBase: '--recording-base',
  recordingAccent: '--recording-accent',
  successBase: '--success-base',
  warningBase: '--warning-base',
  errorBase: '--error-base',
  processingBase: '--processing-base',
  processingAccent: '--processing-accent',
  readyBase: '--ready-base',
  readyAccent: '--ready-accent',
};

/** Every token name the full `ThemeConfig` contract defines, in the shared token map's own order. */
export const FULL_THEME_TOKENS = Object.keys(THEME_TOKEN_CSS_VAR) as ContractThemeTokenKey[];

/**
 * The subset of `FULL_THEME_TOKENS` that Settings' own bespoke `ThemePayload`
 * type (`web-components/SettingsWebComponents/src/types.ts`) still
 * defines and echoes verbatim to its canonical CSS custom property name.
 * Settings predates the Package 0 contract and is missing
 * `successBase`/`errorBase`/`readyBase`/`readyAccent` because the native
 * `AestheticWebPayload` sender Settings itself reads from does not include
 * them on Settings' bridge; this is documented, accepted debt from Package 4
 * (see the roadmap's Package 4 status paragraph), not a new Package 8 defect.
 * `textPrimary`/`separatorColor`/`fieldBorder` are excluded for a different
 * reason (Dark Palette Remediation, 2026-09-17): `hostTheme.ts` publishes
 * these three under `--host-text-primary`/`--host-separator-color`/
 * `--host-field-border` instead of their canonical names, so a
 * palette-aware stylesheet rule in `appearance-settings.css` can derive the
 * real `--text-primary`/`--separator-color`/`--field-border` from them
 * without an `!important` collision against this same inline style. They are
 * derived, not echoed verbatim, so `hostTheme.contract.test.ts` asserts them
 * separately against their `--host-*` names instead of through this list.
 * Settings' own contract test (Companion 02) must assert against this
 * narrower list, not `FULL_THEME_TOKENS`, so the test encodes today's real,
 * accepted contract instead of failing on a known and intentional gap.
 */
export const SETTINGS_THEME_TOKENS: readonly ContractThemeTokenKey[] = FULL_THEME_TOKENS.filter(
  (token) =>
    !(['successBase', 'errorBase', 'readyBase', 'readyAccent'] as const).includes(token as never) &&
    !(['textPrimary', 'separatorColor', 'fieldBorder'] as const).includes(token as never),
);

/**
 * Applies `fixtureOverrides` merged onto `CONTRACT_THEME_FIXTURE` through a
 * consumer's own real theme-apply function, then asserts every token in
 * `expectedTokens` landed on `document.documentElement` under its canonical
 * CSS custom property name with the exact fixture value. Pass a narrower
 * `expectedTokens` list (e.g. `SETTINGS_THEME_TOKENS`) for a consumer that
 * intentionally implements less than the full contract, and never include a
 * token here that the consumer derives instead of echoing verbatim (assert
 * those separately in the calling test, as Companion 04 does for
 * `separatorColor` in `AssistantSession`/`TranscriptionWidget`).
 */
export function assertAppliesThemeTokens(
  apply: (theme: ThemeConfig) => void,
  expectedTokens: readonly ContractThemeTokenKey[],
  fixtureOverrides: Partial<ThemeConfig> = {},
): void {
  const fixture: ThemeConfig = { ...CONTRACT_THEME_FIXTURE, ...fixtureOverrides };
  apply(fixture);
  const style = document.documentElement.style;
  for (const token of expectedTokens) {
    const cssVar = THEME_TOKEN_CSS_VAR[token];
    expect(
      style.getPropertyValue(cssVar),
      `expected ${cssVar} to equal the fixture's ${token} after calling the consumer's apply function`,
    ).toBe(fixture[token]);
  }
}

/**
 * Applies `CONTRACT_FONT_FIXTURE` through a consumer's own real font-apply
 * function and asserts the three canonical `--font-family*` custom
 * properties this repository's `applyHostFonts` implementations always set
 * (`--font-family`, `--font-family-medium`, `--font-family-bold`) all landed
 * with the fixture's exact values.
 */
export function assertAppliesFontTokens(applyFonts: (fonts: FontConfig) => void): void {
  applyFonts(CONTRACT_FONT_FIXTURE);
  const style = document.documentElement.style;
  expect(style.getPropertyValue('--font-family')).toBe(CONTRACT_FONT_FIXTURE.fontFamily);
  expect(style.getPropertyValue('--font-family-medium')).toBe(CONTRACT_FONT_FIXTURE.fontFamilyMedium);
  expect(style.getPropertyValue('--font-family-bold')).toBe(CONTRACT_FONT_FIXTURE.fontFamilyBold);
}
