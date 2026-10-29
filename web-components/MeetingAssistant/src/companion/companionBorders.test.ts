import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(__dirname, '../styles/companion.css'), 'utf8');

describe('companion.css borders', () => {
  it('draws every border one pixel wide, with no accent stripe on cards', () => {
    const widths = [...css.matchAll(/border(?:-(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?)?(?:-width)?\s*:\s*([^;]+);/g)].map((match) => match[1].trim());
    expect(widths.length).toBeGreaterThan(0);
    for (const value of widths) {
      const pixelWidths = [...value.matchAll(/(\d+(?:\.\d+)?)px/g)].map((match) => match[1]);
      for (const width of pixelWidths) expect(width, `border value "${value}"`).toBe('1');
    }
    expect(css).not.toMatch(/\.companion-item--(?:answer|suggestion)/);
  });
});
