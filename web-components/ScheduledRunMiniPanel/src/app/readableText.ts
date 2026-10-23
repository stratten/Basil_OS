const MIN_CONTRAST_RATIO = 4.5;

function parseHex(value: string | undefined): [number, number, number] | null {
  const match = /^#([0-9a-f]{6})$/i.exec((value ?? '').trim());
  if (!match) return null;
  const n = parseInt(match[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function luminance([r, g, b]: [number, number, number]): number {
  const channel = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(foreground: [number, number, number], background: [number, number, number]): number {
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/**
 * Returns replacement text colors when the host's text color cannot be read on its background (for example dark text on a navy surface), or null when the host colors are already readable or are not plain hex values.
 */
export function readableTextOverride(
  backgroundPrimary: string | undefined,
  textPrimary: string | undefined,
): { textPrimary: string; textSecondary: string } | null {
  const background = parseHex(backgroundPrimary);
  const text = parseHex(textPrimary);
  if (!background || !text) return null;
  if (contrastRatio(text, background) >= MIN_CONTRAST_RATIO) return null;
  const white: [number, number, number] = [255, 255, 255];
  const black: [number, number, number] = [0, 0, 0];
  const useWhite = contrastRatio(white, background) >= contrastRatio(black, background);
  return useWhite
    ? { textPrimary: '#ffffff', textSecondary: 'rgba(255, 255, 255, 0.82)' }
    : { textPrimary: '#000000', textSecondary: 'rgba(0, 0, 0, 0.78)' };
}

/** Applies the override to the document root; a no-op when the host colors are readable. */
export function applyReadableTextGuard(
  theme: { backgroundPrimary?: string; textPrimary?: string },
  root: { style: { setProperty(name: string, value: string): void } } = document.documentElement,
): void {
  const override = readableTextOverride(theme.backgroundPrimary, theme.textPrimary);
  if (!override) return;
  root.style.setProperty('--text-primary', override.textPrimary);
  root.style.setProperty('--text-secondary', override.textSecondary);
}
