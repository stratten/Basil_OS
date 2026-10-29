import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('Agent Task capture input surface finish', () => {
  const entry = readFileSync('src/main.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/capture-surface-finish.css', 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import './styles/capture-surface-finish.css';");
    expect(entry).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears only the widget shell, and only under the background-only finish', () => {
    expect(finishCss).toContain(`${SCOPE} :is(`);
    expect(finishCss).toContain('.capture-widget,');
    expect(finishCss).toContain('.capture-widget--loading');
    expect(finishCss.split(SCOPE).length - 1).toBe(1);
    for (const solidSurface of ['.text-followup', '.rich-text-composer', '.capture-reference']) {
      expect(finishCss).not.toContain(solidSurface);
    }
  });
});
