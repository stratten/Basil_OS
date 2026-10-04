import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('Agent Task result window surface finish', () => {
  const resultEntry = readFileSync('src/main.tsx', 'utf8');
  const filePreviewEntry = readFileSync('src/entries/file-preview.tsx', 'utf8');
  const localWebPreviewEntry = readFileSync('src/entries/local-web-preview.tsx', 'utf8');
  const finishCss = readFileSync('src/styles/agent-task-result-surface-finish.css', 'utf8');
  const previewFinishCss = readFileSync('src/styles/preview-surface-finish.css', 'utf8');

  it('opts the Agent Task result window into the background-only metallic finish', () => {
    expect(resultEntry).toContain("import './styles/agent-task-result-surface-finish.css';");
    expect(resultEntry).toContain('enableBackdropSurfaceFinish();');
    expect(resultEntry).not.toContain('preview-surface-finish.css');
  });

  it('opts both preview windows in with the shared preview stylesheet only', () => {
    for (const previewEntry of [filePreviewEntry, localWebPreviewEntry]) {
      expect(previewEntry).toContain("import '../styles/preview-surface-finish.css';");
      expect(previewEntry).toContain('enableBackdropSurfaceFinish();');
      expect(previewEntry).not.toContain('agent-task-result-surface-finish.css');
    }
  });

  it('clears only the preview header, keeping the file body and rendered frame solid', () => {
    expect(previewFinishCss).toContain('html[data-surface-finish="metal_backdrop"] .file-preview-window-header {');
    for (const solidSurface of ['.file-preview-window-body', '.file-preview-window-path', '.file-preview-window-version-row', '.local-web-preview-body', '.file-preview-window {']) {
      expect(previewFinishCss).not.toContain(solidSurface);
    }
    expect(previewFinishCss.match(/html\[data-surface-finish=/g)).toHaveLength(1);
  });

  it('clears only the window chrome, and only under the background-only finish', () => {
    expect(finishCss).toContain('html[data-surface-finish="metal_backdrop"] :is(');
    for (const chrome of ['.sidebar', '.agent-run-rail']) {
      expect(finishCss).toContain(chrome);
    }
    for (const solidSurface of ['.result-container', '.result-section', '.progress-step', '.text-followup', '.rich-text-composer', '.sidebar-search-input']) {
      expect(finishCss).not.toContain(solidSurface);
    }
    expect(finishCss.match(/html\[data-surface-finish=/g)).toHaveLength(1);
  });
});
