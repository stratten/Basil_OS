// @vitest-environment node
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');

const COMPONENTS = {
  'result/HistoryCard.tsx': read('result/HistoryCard.tsx'),
  'sidebar/AgentTaskRow.tsx': read('sidebar/AgentTaskRow.tsx'),
  'approval/ApprovalOverlay.tsx': read('approval/ApprovalOverlay.tsx'),
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
    expect(inline.sort()).toEqual(['approval/ApprovalOverlay.tsx', 'sidebar/AgentTaskRow.tsx']);
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
    expect(COMPONENTS['approval/ApprovalOverlay.tsx']).not.toMatch(/var\(--(?:border|surface)[,)]/);
  });

  it('imports all four stylesheets from components.css', () => {
    const entry = read('../styles/components.css');
    for (const file of Object.keys(STYLESHEETS)) {
      expect(entry).toContain(`@import './components/${file}';`);
    }
  });
});

// The scheduled-task surface: the detail view, every component in scheduled/, and the shared icon chip it draws connections with.
const SCHEDULED_COMPONENTS: Record<string, string> = Object.fromEntries([
  ...readdirSync(resolve(here, 'scheduled'))
    .filter((file) => file.endsWith('.tsx') && !file.endsWith('.test.tsx'))
    .map((file) => [`scheduled/${file}`, read(`scheduled/${file}`)]),
  ['../../../shared/icons/IconChipList.tsx', read('../../../shared/icons/IconChipList.tsx')],
]);
const SCHEDULED_CSS = read('../styles/components/scheduled.css');
const ICON_CHIP_CSS = read('../../../shared/icons/icon-chip.css');
const SCHEDULED_CLASS_TOKEN = /\b(?:scheduled-[a-z_-]+|icon-chip[a-z_-]*|smart-prompt-interpreting)\b/g;

describe('scheduled-task surface style contract', () => {
  it('covers every scheduled component, not just a sample', () => {
    const files = Object.keys(SCHEDULED_COMPONENTS);
    expect(files.length).toBeGreaterThanOrEqual(12);
    for (const expected of ['scheduled/ScheduleControls.tsx', 'scheduled/ScheduledRunHistoryList.tsx', 'scheduled/ScheduledConnectionsField.tsx', 'scheduled/WeekdayChips.tsx']) {
      expect(files).toContain(expected);
    }
  });

  it.each(Object.keys(SCHEDULED_COMPONENTS))('%s has no inline styles and no literal colors', (file) => {
    const source = SCHEDULED_COMPONENTS[file];
    expect(source).not.toMatch(/style=\{/);
    expect(source).not.toMatch(/rgba?\(/);
    expect(source).not.toMatch(/(?<!&)#[0-9a-fA-F]{3,8}\b/);
  });

  it('defines every scheduled and icon-chip class the components reference', () => {
    // The header's state dot also carries the sidebar row's dot classes, which agent-task-row.css owns.
    const css = `${SCHEDULED_CSS}\n${ICON_CHIP_CSS}\n${STYLESHEETS['agent-task-row.css']}`;
    const withoutComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const missing: string[] = [];
    for (const [file, source] of Object.entries(SCHEDULED_COMPONENTS)) {
      for (const token of new Set(withoutComments(source).match(SCHEDULED_CLASS_TOKEN) ?? [])) {
        if (token.endsWith('-')) continue;
        if (!new RegExp(`\\.${token}(?![\\w-])`).test(css)) missing.push(`${file}: ${token}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('uses theme tokens only: no hex or rgba colors, and the one named tile color in the chip sheet', () => {
    expect(SCHEDULED_CSS).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(SCHEDULED_CSS).not.toMatch(/rgba?\(/);
    expect(ICON_CHIP_CSS).not.toMatch(/rgba?\(/);
    expect(ICON_CHIP_CSS.match(/#[0-9a-fA-F]{3,8}\b/g)).toEqual(['#FFFFFF']);
  });

  it('does not use undefined tokens, and sets no text in the low-contrast tertiary gray', () => {
    for (const css of [SCHEDULED_CSS, ICON_CHIP_CSS]) {
      expect(css).not.toMatch(/var\(--(?:border|surface|accent-base)[,)]/);
      expect(css).not.toContain('var(--text-tertiary)');
    }
    for (const source of Object.values(SCHEDULED_COMPONENTS)) {
      expect(source).not.toContain('--accent-base');
      expect(source).not.toContain('current-agent-task-label');
    }
  });

  it('gives every interactive control in the scheduled sheet a keyboard focus ring', () => {
    for (const control of ['scheduled-input', 'scheduled-weekday', 'scheduled-icon-btn', 'scheduled-link-btn', 'scheduled-run.is-navigable', 'scheduled-run__toggle']) {
      expect(SCHEDULED_CSS).toMatch(new RegExp(`\\.${control.replace('.', '\\.')}:focus-visible`));
    }
    expect(ICON_CHIP_CSS).toMatch(/\.icon-chip__remove:focus-visible/);
  });

  it('imports the scheduled sheet, the switch sheet and the chip sheet', () => {
    const entry = read('../styles/components.css');
    expect(entry).toContain("@import './components/scheduled.css';");
    expect(entry).toContain("@import '../../../shared/inputs/switch.css';");
    expect(ICON_CHIP_CSS.length).toBeGreaterThan(0);
    expect(SCHEDULED_COMPONENTS['../../../shared/icons/IconChipList.tsx']).toContain("import './icon-chip.css';");
  });

  it('does not let the run list scroll inside the page or cap the connection chips', () => {
    expect(SCHEDULED_CSS).not.toMatch(/\.scheduled-runs[^{]*\{[^}]*(?:max-height|overflow-y)/);
    expect(ICON_CHIP_CSS).not.toMatch(/max-height|overflow-y/);
  });
});
