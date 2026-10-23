import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('Skill reconciliation workspace surface finish', () => {
  const entry = readFileSync('src/main.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/reconciliation-surface-finish.css', 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import './styles/reconciliation-surface-finish.css';");
    expect(entry).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears the action list while the detail pane stays solid', () => {
    expect(finishCss).toContain(`${SCOPE} .action-list-pane {\n  background: transparent;\n}`);
    expect(finishCss).toContain(`${SCOPE} .action-detail-pane {\n  background: var(--background-primary);\n}`);
    expect(finishCss.split(SCOPE).length - 1).toBe((finishCss.match(/\{/g) ?? []).length);
  });
});
