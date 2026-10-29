// @vitest-environment node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');

const COMPONENTS = {
  'result/HistoryCard.tsx': read('result/HistoryCard.tsx'),
  'sidebar/AgentTaskRow.tsx': read('sidebar/AgentTaskRow.tsx'),
  'ApprovalOverlay.tsx': read('ApprovalOverlay.tsx'),
  'result/ResultAttachments.tsx': read('result/ResultAttachments.tsx'),
};

const STYLESHEETS = {
  'history-card.css': read('../styles/components/history-card.css'),
  'agent-task-row.css': read('../styles/components/agent-task-row.css'),
  'approval-details.css': read('../styles/components/approval-details.css'),
  'result-attachments.css': read('../styles/components/result-attachments.css'),
};

const ALL_CSS = Object.values(STYLESHEETS).join('\n');

// Every class name these four components introduced when their inline styles moved to CSS.
const NEW_CLASS_TOKEN = /\b(?:agent-task-row|history-card|result-files|result-file-row|result-refs|approval-(?:section|tag|link-button|script-preview|field-label|sensitive-input|reason|pattern|high-risk-notice|remember)|command-display--collapsed|action-btn--neutral)[a-z_-]*/g;

describe('AgentTaskResult inline-style cleanup contract', () => {
  it('keeps only the two genuinely dynamic inline styles across the four components', () => {
    const inline = Object.entries(COMPONENTS).flatMap(([file, source]) =>
      (source.match(/style=\{/g) ?? []).map(() => file),
    );
    expect(inline.sort()).toEqual(['ApprovalOverlay.tsx', 'sidebar/AgentTaskRow.tsx']);
  });

  it.each(Object.keys(COMPONENTS))('%s has no literal colors', (file) => {
    const source = COMPONENTS[file as keyof typeof COMPONENTS];
    expect(source).not.toMatch(/rgba?\(/);
    expect(source).not.toMatch(/(?<!&)#[0-9a-fA-F]{3,8}\b/);
  });

  it('defines every class the components reference', () => {
    const missing: string[] = [];
    for (const [file, source] of Object.entries(COMPONENTS)) {
      for (const token of new Set(source.match(NEW_CLASS_TOKEN) ?? [])) {
        if (!new RegExp(`\\.${token}(?![\\w-])`).test(ALL_CSS)) missing.push(`${file}: ${token}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('finds the new classes at all (guards the pattern itself)', () => {
    const tokens = new Set(Object.values(COMPONENTS).flatMap((source) => source.match(NEW_CLASS_TOKEN) ?? []));
    expect(tokens.size).toBeGreaterThan(40);
    expect(tokens.has('history-card__alert--warning')).toBe(true);
    expect(tokens.has('result-files__retrieved--after-changed')).toBe(true);
    expect(tokens.has('agent-task-row__detach--below-trash')).toBe(true);
    expect(tokens.has('approval-sensitive-input')).toBe(true);
  });

  it.each(Object.keys(STYLESHEETS))('%s uses theme tokens, with no hex or rgba colors', (file) => {
    const css = STYLESHEETS[file as keyof typeof STYLESHEETS];
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/rgba\(/);
  });

  it('allows only the two named accents that have no theme token', () => {
    const literals = ALL_CSS.match(/rgb\([^)]*\)/g) ?? [];
    expect(literals.sort()).toEqual(['rgb(147 130 220)', 'rgb(255 0 0)']);
  });

  it('does not reference the undefined --border and --surface tokens', () => {
    expect(ALL_CSS).not.toMatch(/var\(--(?:border|surface)[,)]/);
    expect(COMPONENTS['ApprovalOverlay.tsx']).not.toMatch(/var\(--(?:border|surface)[,)]/);
  });

  it('imports all four stylesheets from components.css', () => {
    const entry = read('../styles/components.css');
    for (const file of Object.keys(STYLESHEETS)) {
      expect(entry).toContain(`@import './components/${file}';`);
    }
  });
});
