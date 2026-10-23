import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const windows = [
  {
    name: 'Assistant session',
    entry: 'src/entries/assistant-session.tsx',
    stylesheet: 'assistant-session-surface-finish.css',
    chrome: ['.assistant-session-shell'],
    solid: ['.assistant-session-result__output', '.assistant-session-result__edit-textarea', '.assistant-session-typed-input'],
  },
  {
    name: 'Assistant output history',
    entry: 'src/entries/assistant-output-history.tsx',
    stylesheet: 'assistant-output-history-surface-finish.css',
    chrome: ['.assistant-output-history-shell', '.assistant-output-history-sidebar'],
    solid: ['.assistant-output-history-detail', '.assistant-output-history-sidebar__search-wrap'],
  },
];

describe.each(windows)('$name window surface finish', ({ entry, stylesheet, chrome, solid }) => {
  const entrySource = readFileSync(entry, 'utf8');
  const finishCss = readFileSync(`src/styles/${stylesheet}`, 'utf8');

  it('opts the window into the background-only metallic finish', () => {
    expect(entrySource).toContain(`import '../styles/${stylesheet}';`);
    expect(entrySource).toContain('enableBackdropSurfaceFinish();');
  });

  it('clears only the window chrome, and only under the background-only finish', () => {
    expect(finishCss).toContain('html[data-surface-finish="metal_backdrop"] :is(');
    for (const selector of chrome) {
      expect(finishCss).toContain(selector);
    }
    for (const selector of solid) {
      expect(finishCss).not.toContain(selector);
    }
    expect(finishCss.match(/html\[data-surface-finish=/g)).toHaveLength(1);
  });
});

describe('Assistant windows keep their own finish stylesheets', () => {
  it('does not cross-import the other window opt-in', () => {
    expect(readFileSync('src/entries/assistant-session.tsx', 'utf8')).not.toContain('assistant-output-history-surface-finish.css');
    expect(readFileSync('src/entries/assistant-output-history.tsx', 'utf8')).not.toContain('assistant-session-surface-finish.css');
  });
});
