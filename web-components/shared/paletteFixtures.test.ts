// @vitest-environment jsdom
import { describe, expect, it } from 'vitest';
import { applyHostTheme } from './webTheme';
import { ALL_PALETTE_FIXTURES } from './paletteFixtures';

describe('palette fixture harness', () => {
  for (const { name, palette, expectedColorScheme } of ALL_PALETTE_FIXTURES) {
    it(`applies the ${name} palette's full token set and resolves color-scheme: ${expectedColorScheme}`, () => {
      applyHostTheme(palette);
      const style = document.documentElement.style;
      expect(style.getPropertyValue('--background-primary')).toBe(palette.backgroundPrimary);
      expect(style.getPropertyValue('--primary')).toBe(palette.primary);
      expect(style.getPropertyValue('--text-primary')).toBe(palette.textPrimary);
      expect(style.getPropertyValue('--success-base')).toBe(palette.successBase);
      expect(style.getPropertyValue('--ready-accent')).toBe(palette.readyAccent);
      expect(style.getPropertyValue('color-scheme')).toBe(expectedColorScheme);
    });
  }
});
