import { relativeLuminance } from './appearanceTokenContract';
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
}

export interface FontConfig {
  fontFamily?: string;
  fontFamilyMedium?: string;
  fontFamilyBold?: string;
}

type CssThemeTokenKey = Exclude<keyof ThemeConfig, 'surfaceFinish'>;

const themeTokenMap: Readonly<Record<CssThemeTokenKey, string>> = {
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

export function applyHostTheme(theme?: ThemeConfig): void {
  if (!theme || typeof document === 'undefined') return;

  const root = document.documentElement;
  for (const [themeKey, cssToken] of Object.entries(themeTokenMap) as [CssThemeTokenKey, string][]) {
    const value = theme[themeKey];
    if (value) root.style.setProperty(cssToken, value);
  }

  const colorScheme = colorSchemeFor(theme.backgroundPrimary);
  if (colorScheme) root.style.setProperty('color-scheme', colorScheme);

  applySurfaceFinish(theme.surfaceFinish);
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
