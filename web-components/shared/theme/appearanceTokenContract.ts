export type AppearanceRgbColor = readonly [number, number, number];

export const derivedSurfaceTokens = ['surfaceRaised', 'surfaceSunken', 'surfaceOverlay', 'surfaceSelected', 'surfaceHover', 'surfaceDisabled'] as const;
export const derivedTextTokens = ['textSecondary', 'textTertiary', 'textOnPrimary', 'textOnSuccess', 'textOnWarning', 'textOnError'] as const;
export const derivedStructuralTokens = ['separator', 'fieldBorder', 'focusRing', 'shadow'] as const;
export const fixedSemanticStateTokens = ['recordingBase', 'recordingAccent', 'successBase', 'warningBase', 'errorBase', 'processingBase', 'processingAccent', 'readyBase', 'readyAccent'] as const;

export const appearanceTokenContract = {
  derivedSurfaceTokens,
  derivedTextTokens,
  derivedStructuralTokens,
  fixedSemanticStateTokens,
} as const;

export function contrastRatio(foreground: AppearanceRgbColor, background: AppearanceRgbColor): number {
  const foregroundLuminance = relativeLuminance(foreground);
  const backgroundLuminance = relativeLuminance(background);
  const lighter = Math.max(foregroundLuminance, backgroundLuminance);
  const darker = Math.min(foregroundLuminance, backgroundLuminance);
  return (lighter + 0.05) / (darker + 0.05);
}

export function meetsMinimumContrast(
  foreground: AppearanceRgbColor,
  background: AppearanceRgbColor,
  isLargeText = false,
): boolean {
  return contrastRatio(foreground, background) >= (isLargeText ? 3 : 4.5);
}

export function relativeLuminance(color: AppearanceRgbColor): number {
  validateRgbColor(color);
  return (0.2126 * linearizeSrgb(color[0])) + (0.7152 * linearizeSrgb(color[1])) + (0.0722 * linearizeSrgb(color[2]));
}

function linearizeSrgb(component: number): number {
  return component <= 0.04045 ? component / 12.92 : ((component + 0.055) / 1.055) ** 2.4;
}

function validateRgbColor(color: AppearanceRgbColor): void {
  if (color.length !== 3 || color.some((component) => !Number.isFinite(component) || component < 0 || component > 1)) {
    throw new RangeError('Appearance RGB components must be finite values from 0 through 1.');
  }
}
