import { contrastRatio, relativeLuminance } from './appearanceTokenContract';
import { markHostThemeApplied } from './hostThemeSignal';
import { applySurfaceFinish } from './surfaceFinish';

export interface ThemeConfig {
  backgroundPrimary?: string;
  backgroundSecondary?: string;
  backgroundTertiary?: string;
  primary?: string;
  secondary?: string;
  textPrimary?: string;
  textSecondary?: string;
  textTertiary?: string;
  separatorColor?: string;
  fieldBorder?: string;
  recordingBase?: string;
  recordingAccent?: string;
  successBase?: string;
  warningBase?: string;
  errorBase?: string;
  processingBase?: string;
  processingAccent?: string;
  readyBase?: string;
  readyAccent?: string;
  surfaceFinish?: string;
  /** App-wide text size multiplier published by the host; one of 0.9, 1.0, 1.1, 1.25 or 1.4. */
  textScale?: number;
}

export interface FontConfig {
  fontFamily?: string;
  fontFamilyMedium?: string;
  fontFamilyBold?: string;
}

type CssThemeTokenKey = Exclude<keyof ThemeConfig, 'surfaceFinish' | 'separatorColor' | 'fieldBorder' | 'textScale'>;

/**
 * Strength of the shared interior divider: the theme's secondary color at this opacity over whatever surface the line sits on.
 * macOS's own `separatorColor` (the value the host publishes as `separatorColor`) is far heavier on current releases, so it is deliberately not used.
 */
export const SEPARATOR_SECONDARY_MIX_PERCENT = 18;

/**
 * Strength of the shared input and control outline: the theme's secondary color at this opacity.
 * The host publishes `fieldBorder` as a hex string, which cannot carry the 20% opacity it is defined with, so the page would receive the fully opaque secondary color; the page therefore derives the outline itself.
 */
export const FIELD_BORDER_SECONDARY_MIX_PERCENT = 20;

/** The one derivation every window uses for `--field-border`; falls back to the already-applied `--secondary` when the theme carries none. */
export function deriveFieldBorder(secondary?: string): string {
  return `color-mix(in srgb, ${secondary?.trim() || 'var(--secondary)'} ${FIELD_BORDER_SECONDARY_MIX_PERCENT}%, transparent)`;
}

/** The one derivation every window uses for `--separator-color`; falls back to the already-applied `--secondary` when the theme carries none. */
export function deriveSeparatorColor(secondary?: string): string {
  return `color-mix(in srgb, ${secondary?.trim() || 'var(--secondary)'} ${SEPARATOR_SECONDARY_MIX_PERCENT}%, transparent)`;
}

/** A white label on a fill is kept for as long as it meets the WCAG minimum for large text or user interface components; below that the label turns black. */
const TEXT_ON_FILL_MIN_WHITE_CONTRAST = 3;

/** The one derivation every window uses for the label color on a solid fill: white while it stays legible on the fill, otherwise black. Returns undefined when the fill is not a plain hex or rgb color. */
export function deriveTextOnColor(fill?: string): string | undefined {
  const rgb = parseRgbColor(fill);
  if (!rgb) return undefined;
  return contrastRatio([1, 1, 1], rgb) >= TEXT_ON_FILL_MIN_WHITE_CONTRAST ? '#ffffff' : '#000000';
}

type TextOnFillThemeKey = 'primary' | 'secondary' | 'successBase' | 'warningBase' | 'errorBase' | 'processingBase' | 'recordingBase';

/** Each solid fill token that carries a label, with the `--text-on-*` token that holds the label color for it. */
const textOnFillTokens: ReadonlyArray<{ themeKey: TextOnFillThemeKey; fillToken: string; textToken: string }> = [
  { themeKey: 'primary', fillToken: '--primary', textToken: '--text-on-primary' },
  { themeKey: 'secondary', fillToken: '--secondary', textToken: '--text-on-secondary' },
  { themeKey: 'successBase', fillToken: '--success-base', textToken: '--text-on-success' },
  { themeKey: 'warningBase', fillToken: '--warning-base', textToken: '--text-on-warning' },
  { themeKey: 'errorBase', fillToken: '--error-base', textToken: '--text-on-error' },
  { themeKey: 'processingBase', fillToken: '--processing-base', textToken: '--text-on-processing' },
  { themeKey: 'recordingBase', fillToken: '--recording-base', textToken: '--text-on-recording' },
];

/**
 * Publishes `--text-on-primary`, `--text-on-secondary`, `--text-on-success`, `--text-on-warning`, `--text-on-error`, `--text-on-processing` and `--text-on-recording` on the document root.
 * Each is derived from the supplied fill color, or from the fill token already applied to the page when the theme does not carry one, so a theme that omits `errorBase` still gets a label color matching the stylesheet's error fill.
 */
export function applyTextOnColorTokens(theme: Pick<ThemeConfig, TextOnFillThemeKey>): void {
  if (typeof document === 'undefined') return;

  const root = document.documentElement;
  const applied = getComputedStyle(root);
  for (const { themeKey, fillToken, textToken } of textOnFillTokens) {
    const textColor = deriveTextOnColor(theme[themeKey]?.trim() || applied.getPropertyValue(fillToken).trim());
    if (textColor) root.style.setProperty(textToken, textColor);
  }
}

const themeTokenMap: Readonly<Record<CssThemeTokenKey, string>> = {
  backgroundPrimary: '--background-primary',
  backgroundSecondary: '--background-secondary',
  backgroundTertiary: '--background-tertiary',
  primary: '--primary',
  secondary: '--secondary',
  textPrimary: '--text-primary',
  textSecondary: '--text-secondary',
  textTertiary: '--text-tertiary',
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

/** The smallest and largest text size multipliers the host offers; a published value outside them is clamped. */
export const MIN_TEXT_SCALE = 0.9;
export const MAX_TEXT_SCALE = 1.4;

/** The multiplier to apply for a published value: clamped to the offered range, or undefined when it is not a finite number so the page keeps its current size. */
export function normalizeTextScale(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
  return Math.min(MAX_TEXT_SCALE, Math.max(MIN_TEXT_SCALE, value));
}

export function applyHostTheme(theme?: ThemeConfig): void {
  if (!theme || typeof document === 'undefined') return;

  const root = document.documentElement;
  for (const [themeKey, cssToken] of Object.entries(themeTokenMap) as [CssThemeTokenKey, string][]) {
    const value = theme[themeKey];
    if (value) root.style.setProperty(cssToken, value);
  }
  applyTextOnColorTokens(theme);
  // Dividers and header borders are derived from the theme, never taken from the host's system separator color.
  root.style.setProperty('--separator-color', deriveSeparatorColor(theme.secondary));
  root.style.setProperty('--field-border', deriveFieldBorder(theme.secondary));

  const colorScheme = colorSchemeFor(theme.backgroundPrimary);
  if (colorScheme) root.style.setProperty('color-scheme', colorScheme);

  const textScale = normalizeTextScale(theme.textScale);
  if (textScale !== undefined) root.style.setProperty('--text-scale', String(textScale));

  applySurfaceFinish(theme.surfaceFinish);
  markHostThemeApplied();
}

export function applyHostFonts(fonts?: FontConfig): void {
  if (!fonts || typeof document === 'undefined') return;

  const root = document.documentElement;
  if (fonts.fontFamily) {
    root.style.setProperty('--font-family', fonts.fontFamily);
    root.style.setProperty('--font-family-light', fonts.fontFamily);
  }
  if (fonts.fontFamilyMedium) root.style.setProperty('--font-family-medium', fonts.fontFamilyMedium);
  if (fonts.fontFamilyBold) {
    root.style.setProperty('--font-family-bold', fonts.fontFamilyBold);
    root.style.setProperty('--font-family-semibold', fonts.fontFamilyBold);
  }
}

function colorSchemeFor(color: string | undefined): 'dark' | 'light' | undefined {
  const rgb = parseRgbColor(color);
  if (!rgb) return undefined;
  return relativeLuminance(rgb) < 0.5 ? 'dark' : 'light';
}

function parseRgbColor(color: string | undefined): readonly [number, number, number] | undefined {
  if (!color) return undefined;

  const hexMatch = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(color.trim());
  if (hexMatch) {
    const hex = hexMatch[1].length === 3
      ? hexMatch[1].split('').map((component) => component.repeat(2)).join('')
      : hexMatch[1];
    return [Number.parseInt(hex.slice(0, 2), 16) / 255, Number.parseInt(hex.slice(2, 4), 16) / 255, Number.parseInt(hex.slice(4, 6), 16) / 255];
  }

  const rgbMatch = /^rgba?\(\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)(?:\s*,\s*(?:\d+(?:\.\d+)?|\.\d+))?\s*\)$/i.exec(color.trim());
  if (!rgbMatch) return undefined;

  const rgb = [Number(rgbMatch[1]) / 255, Number(rgbMatch[2]) / 255, Number(rgbMatch[3]) / 255] as const;
  return rgb.every((component) => component >= 0 && component <= 1) ? rgb : undefined;
}
