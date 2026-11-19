// @vitest-environment node

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const css = readFileSync(fileURLToPath(new URL('./inline-delete-confirm.css', import.meta.url)), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

describe('inline-delete-confirm.css', () => {
  it('styles itself with tokens only: no hex colors and no rgb or rgba literals', () => {
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/\brgba?\(/);
  });

  it('reads the theme tokens that every host package defines', () => {
    for (const token of ['--text-primary', '--background-primary', '--separator-color', '--error-base', '--padding-s', '--padding-xs', '--border-thin', '--corner-radius-small', '--font-family-medium', '--font-size-footnote', '--font-size-status-tiny']) {
      expect(css, token).toContain(`var(${token})`);
    }
  });

  it('keeps the stacked modifier scoped to its own class', () => {
    expect(css).toContain('.inline-delete-confirm--stacked {');
    expect(css).toContain('.inline-delete-confirm--stacked .inline-delete-confirm__label {');
  });
});
