import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const SCOPE = 'html[data-surface-finish="metal_backdrop"]';

describe('Profile, memory, and skills editor surface finish', () => {
  const entry = readFileSync('src/entries/profile-editor.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/profile-editor-surface-finish.css', 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entry).toContain("import '../styles/profile-editor-surface-finish.css';");
    expect(entry).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears only the window header, leaving the editor content solid', () => {
    expect(finishCss).toContain(`${SCOPE} .profile-editor-window-header {\n  background: transparent;\n}`);
    expect(finishCss.split(SCOPE).length - 1).toBe(1);
    expect(finishCss).not.toContain('.profile-editor-content');
  });
});
