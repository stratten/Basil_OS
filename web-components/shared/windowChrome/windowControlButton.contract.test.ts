// @vitest-environment node

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(fileURLToPath(new URL('./window-control-button.css', import.meta.url)), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

describe('window-control-button.css', () => {
  it('fills the circle from the theme secondary color (the glyph stroke color) with the default blue only as a fallback', () => {
    expect(css).toMatch(/\.basil-window-control-circle \{\s*fill: color-mix\(in srgb, var\(--secondary, #33559b\) 15%, transparent\);\s*\}/);
  });

  it('contains no white, black, or rgb literal colors', () => {
    expect(css).not.toMatch(/#(?:fff|ffffff|000|000000)\b/i);
    expect(css).not.toMatch(/\brgba?\(/);
  });

  it('rotates the collapsed chevron a quarter turn and respects reduced motion', () => {
    expect(css).toContain('.basil-window-control-chevron.is-collapsed {\n  transform: rotate(-90deg);\n}');
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\) \{\s*\.basil-window-control-chevron \{\s*transition: none;/);
  });
});
