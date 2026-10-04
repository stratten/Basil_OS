import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

function ruleSelectors(css: string, declaration: string): string {
  const pattern = new RegExp(`([^{}]*)\\{\\s*${declaration}\\s*\\}`, 'g');
  return [...css.replace(/\/\*[\s\S]*?\*\//g, '').matchAll(pattern)].map((match) => match[1]).join('\n');
}

describe('Power user guide window surface finish', () => {
  const entry = readFileSync('src/entries/power-user-guide-panel.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/power-user-guide-surface-finish.css', 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import '../styles/power-user-guide-surface-finish.css'");
    expect(entry).toContain('enableBackdropSurfaceFinish()');
  });

  it('scopes every rule to the background-only finish', () => {
    expect(finishCss.split(SCOPE).length - 1).toBe((finishCss.match(/\{/g) ?? []).length);
  });

  it('clears the shell and sidebar while the guide text pane stays solid', () => {
    const cleared = ruleSelectors(finishCss, 'background: transparent;');
    const solid = ruleSelectors(finishCss, 'background: var\\(--background-primary\\);');
    expect(cleared).toContain('.pug-shell');
    expect(cleared).toContain('.pug-sidebar');
    expect(cleared).not.toContain('.pug-content');
    expect(solid).toContain('.pug-content');
  });
});
