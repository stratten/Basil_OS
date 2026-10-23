import type { ThemeConfig } from './webTheme';

/**
 * Three representative palette categories used to prove the theming pipeline
 * behaves correctly across the shapes of palette a real user can configure,
 * per Package 8's own tracking-table wording ("browser fixtures for default,
 * dark-gray/off-white, and custom palettes"). These are illustrative fixture
 * values chosen to exercise the pipeline's light/dark color-scheme derivation
 * and full-token coverage -- they are not asserted to equal any specific
 * production default; `AestheticSystem`'s own Swift-side defaults remain the
 * single source of truth for what a fresh install actually ships.
 */
export const DEFAULT_LIGHT_PALETTE_FIXTURE: Required<ThemeConfig> = {
  backgroundPrimary: '#FFFFFE',
  backgroundSecondary: '#F5F5F4',
  backgroundTertiary: '#EBEBEA',
  primary: '#2563EB',
  secondary: '#7C3AED',
  textPrimary: '#111318',
  textSecondary: '#4B5563',
  textTertiary: '#9CA3AF',
  separatorColor: 'rgba(17, 19, 24, 0.12)',
  fieldBorder: 'rgba(17, 19, 24, 0.24)',
  recordingBase: '#DC2626',
  recordingAccent: '#FCA5A5',
  successBase: '#16A34A',
  warningBase: '#D97706',
  errorBase: '#DC2626',
  processingBase: '#7C3AED',
  processingAccent: '#DDD6FE',
  readyBase: '#059669',
  readyAccent: '#A7F3D0',
};

/**
 * A dark-mode-style palette: a dark-gray background paired with off-white
 * text, mirroring the exact scenario Package 6's own deferred runtime
 * spot-check already names ("dark-gray/off-white preset"). `backgroundPrimary`
 * is deliberately dark enough (relative luminance well under 0.5) to exercise
 * `webTheme.ts`'s `colorSchemeFor` derivation down the `'dark'` branch.
 */
export const DARK_GRAY_OFF_WHITE_PALETTE_FIXTURE: Required<ThemeConfig> = {
  backgroundPrimary: '#2B2B2E',
  backgroundSecondary: '#38383C',
  backgroundTertiary: '#454549',
  primary: '#60A5FA',
  secondary: '#A78BFA',
  textPrimary: '#F5F5F0',
  textSecondary: '#D1D1CB',
  textTertiary: '#A3A39D',
  separatorColor: 'rgba(245, 245, 240, 0.14)',
  fieldBorder: 'rgba(245, 245, 240, 0.28)',
  recordingBase: '#F87171',
  recordingAccent: '#FCA5A5',
  successBase: '#4ADE80',
  warningBase: '#FBBF24',
  errorBase: '#F87171',
  processingBase: '#A78BFA',
  processingAccent: '#DDD6FE',
  readyBase: '#34D399',
  readyAccent: '#A7F3D0',
};

/**
 * A saturated, deliberately non-default "custom" palette a user might pick
 * via the color pickers -- proves the pipeline does not silently clamp,
 * round, or reject unusual-but-valid values.
 */
export const CUSTOM_PALETTE_FIXTURE: Required<ThemeConfig> = {
  backgroundPrimary: '#0B1F0F',
  backgroundSecondary: '#123018',
  backgroundTertiary: '#194020',
  primary: '#FF6B35',
  secondary: '#F7C948',
  textPrimary: '#F0FFF4',
  textSecondary: '#B8E6C4',
  textTertiary: '#7FBF97',
  separatorColor: 'rgba(240, 255, 244, 0.16)',
  fieldBorder: 'rgba(240, 255, 244, 0.3)',
  recordingBase: '#FF3860',
  recordingAccent: '#FFB3C6',
  successBase: '#00D68F',
  warningBase: '#FFC048',
  errorBase: '#FF3860',
  processingBase: '#9B5DE5',
  processingAccent: '#E0C3FC',
  readyBase: '#00D68F',
  readyAccent: '#B8FFE0',
};

export const ALL_PALETTE_FIXTURES = [
  { name: 'default light', palette: DEFAULT_LIGHT_PALETTE_FIXTURE, expectedColorScheme: 'light' as const },
  { name: 'dark-gray/off-white', palette: DARK_GRAY_OFF_WHITE_PALETTE_FIXTURE, expectedColorScheme: 'dark' as const },
  { name: 'custom saturated', palette: CUSTOM_PALETTE_FIXTURE, expectedColorScheme: 'dark' as const },
] as const;
