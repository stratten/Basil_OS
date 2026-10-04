import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('Model download panel surface finish', () => {
  const entry = readFileSync('src/entries/model-download-mini-panel.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/model-download-surface-finish.css', 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import '../styles/model-download-surface-finish.css'");
    expect(entry).toContain('enableBackdropSurfaceFinish()');
  });

  it('clears only the panel body, and only under the background-only finish', () => {
    expect(finishCss).toContain(`${SCOPE} .model-download-panel {\n  background: transparent;\n}`);
    expect(finishCss.split(SCOPE).length - 1).toBe((finishCss.match(/\{/g) ?? []).length);
  });
});
