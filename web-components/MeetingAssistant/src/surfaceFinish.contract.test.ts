import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const assistantEntry = readFileSync('src/entries/meeting-assistant.tsx', 'utf8');
const analysisEntry = readFileSync('src/entries/meeting-analysis.tsx', 'utf8');
const assistantCss = readFileSync('src/styles/meeting-assistant-surface-finish.css', 'utf8');
const analysisCss = readFileSync('src/styles/meeting-analysis-surface-finish.css', 'utf8');

describe('Meeting windows surface finish', () => {
  it('opts each meeting window into the background-only metallic finish with its own stylesheet', () => {
    expect(assistantEntry).toContain("import '../styles/meeting-assistant-surface-finish.css';");
    expect(assistantEntry).toContain('enableBackdropSurfaceFinish();');
    expect(assistantEntry).not.toContain('meeting-analysis-surface-finish.css');
    expect(analysisEntry).toContain("import '../styles/meeting-analysis-surface-finish.css';");
    expect(analysisEntry).toContain('enableBackdropSurfaceFinish();');
    expect(analysisEntry).not.toContain('meeting-assistant-surface-finish.css');
  });

  it('clears only the Meeting Assistant chrome and keeps the transcript, cards, and fields solid', () => {
    expect(assistantCss).toContain('html[data-surface-finish="metal_backdrop"] :is(');
    for (const chrome of ['.meeting-assistant-surface', '.meeting-window-chrome', '.meeting-body', '.meeting-history-sidebar', '.meeting-history-sidebar--collapsed']) {
      expect(assistantCss).toContain(chrome);
    }
    for (const solid of ['.meeting-transcript-panel', '.meeting-transcript-tools-card', '.meeting-analysis-card', '.meeting-card', '.meeting-metadata', '.meeting-participant-field']) {
      expect(assistantCss).not.toContain(solid);
    }
    expect(assistantCss.match(/html\[data-surface-finish=/g)).toHaveLength(1);
  });

  it('clears the Meeting Analysis chrome and gives the analysis content a solid theme fill', () => {
    expect(analysisCss).toContain('.meeting-analysis-surface,\n  .meeting-analysis-surface .meeting-window-chrome\n) {\n  background: transparent;');
    expect(analysisCss).toContain('html[data-surface-finish="metal_backdrop"] .meeting-analysis-content {\n  background: var(--background-primary);');
    expect(analysisCss.match(/html\[data-surface-finish=/g)).toHaveLength(2);
    expect(analysisCss.match(/html\[data-surface-finish="metal_backdrop"\]/g)).toHaveLength(2);
  });
});
