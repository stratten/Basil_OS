// @vitest-environment node
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');

const COMPONENT_FILES = readdirSync(here).filter(file => /^Checklist.*\.tsx$/.test(file) && !/\.test\./.test(file));
const COMPONENTS = Object.fromEntries(COMPONENT_FILES.map(file => [file, read(file)]));
const CSS = read('../../styles/components/detail-tray/checklist.css');
const ROW_CSS = read('../../styles/components/agent-task-row.css');
const RAIL_CSS = read('../../styles/components/detail-tray/agent-run-rail.css');
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '');

describe('checklist styling contract', () => {
  it('finds the checklist components, so the checks below cannot pass vacuously', () => {
    expect(COMPONENT_FILES).toEqual(expect.arrayContaining([
      'ChecklistAddForm.tsx', 'ChecklistItemDetail.tsx', 'ChecklistNotesEditor.tsx', 'ChecklistOverviewSection.tsx', 'ChecklistRailPill.tsx', 'ChecklistStatusGlyph.tsx', 'ChecklistWindow.tsx',
    ]));
  });

  it.each(COMPONENT_FILES)('%s uses no inline styles and no literal colors', file => {
    const source = COMPONENTS[file];
    expect(source).not.toMatch(/style=\{/);
    expect(source).not.toMatch(/rgba?\(/);
    expect(source).not.toMatch(/(?<!&)#[0-9a-fA-F]{3,8}\b/);
  });

  it('defines every class the components reference', () => {
    const missing: string[] = [];
    for (const [file, source] of Object.entries(COMPONENTS)) {
      const classNames = new Set(source.match(/\b(?:checklist-[a-z_-]+|agent-run-rail-checklist[a-z_-]*)/g) ?? []);
      for (const token of classNames) {
        // Element ids and aria ids share the prefix; only class selectors need a rule.
        if (/^checklist-(?:window-title|panel|tab-items|tab-notes|notes-text|notes-count)$/.test(token)) continue;
        // A class built from a template (checklist-glyph--${status}) is checked state by state below.
        if (token.endsWith('--')) continue;
        if (!new RegExp(`\\.${token}(?![\\w-])`).test(CSS)) missing.push(`${file}: ${token}`);
      }
    }
    expect(missing).toEqual([]);
  });

  it('styles every status variant of the glyph the component can build', () => {
    for (const status of ['in_progress', 'waiting_user', 'waiting_external', 'done', 'dropped']) {
      expect(CSS).toContain(`.checklist-glyph--${status} `);
    }
  });

  it('uses theme and semantic-state tokens only, with no hex, rgba, or fixed-pixel font sizes', () => {
    const css = stripComments(CSS);
    expect(css).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(css).not.toMatch(/rgba?\(/);
    for (const declaration of css.match(/font-size\s*:[^;]+;/g) ?? []) {
      expect(declaration).toMatch(/var\(--font-size-/);
    }
    expect(css).not.toMatch(/var\(--(?:border|surface)[,)]/);
  });

  it('draws state roles from the shared tokens: amber for the reader, green for done, teal for waiting on others', () => {
    expect(CSS).toMatch(/\.checklist-glyph--waiting_user\s*\{\s*color:\s*var\(--warning-base\)/);
    expect(CSS).toMatch(/\.checklist-glyph--done\s*\{\s*color:\s*var\(--success-base\)/);
    expect(CSS).toMatch(/\.checklist-glyph--waiting_external\s*\{\s*color:\s*var\(--notice-base\)/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist-pill\.is-attention\s*\{[^}]*var\(--warning-base\)/);
  });

  it('is not the stop button red: the pill never uses the error color', () => {
    const pillRules = stripComments(CSS).match(/\.agent-run-rail-checklist[^{]*\{[^}]*\}/g) ?? [];
    expect(pillRules.length).toBeGreaterThan(3);
    for (const rule of pillRules) expect(rule).not.toContain('--error-');
  });

  it('keeps the rail pill inside the 44px rail, wrapping its two halves instead of overflowing at a large text scale', () => {
    expect(RAIL_CSS).toMatch(/\.agent-run-rail\s*\{[^}]*flex:\s*0 0 44px/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist\s*\{[^}]*padding:\s*0 var\(--padding-xs\)/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist-pill\s*\{[^}]*width:\s*100%/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist-pill\s*\{[^}]*flex-wrap:\s*wrap/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist-pill\s*\{[^}]*font-size:\s*var\(--font-size-status-tiny\)/);
    expect(CSS).toMatch(/\.agent-run-rail-checklist\s*\{[^}]*border-bottom:\s*var\(--border-thin\) solid var\(--separator-color\)/);
  });

  it('draws a text field focus ring as the field\'s own one-pixel border, so the scrolling panel cannot clip it', () => {
    const css = stripComments(CSS);
    const focus = css.match(/\.checklist-field__input:focus,\s*\.checklist-field__input:focus-visible\s*\{([^}]*)\}/);
    expect(focus).not.toBeNull();
    expect(focus![1]).toMatch(/outline:\s*none/);
    expect(focus![1]).toMatch(/border-color:\s*var\(--secondary\)/);
    expect(focus![1]).toMatch(/box-shadow:\s*none/);
    expect(stripComments(CSS)).toMatch(/\.checklist-field__input\s*\{[^}]*border:\s*var\(--border-thin\) solid/);
    expect(css).not.toMatch(/\.checklist-field__input:focus-visible\s*\{[^}]*outline:\s*var/);
    expect(css).toMatch(/\.checklist-window__panel\s*\{[^}]*padding:\s*var\(--padding-xs\);/);
  });

  it('styles the schedule carry-over options with the shared switch and classes, not inline styles', () => {
    const field = read('../scheduled/ScheduledChainField.tsx');
    expect(field).toMatch(/<Switch\b/);
    expect(field).toContain('scheduled-switch-row');
    expect(field).not.toMatch(/style=/);
    expect(stripComments(CSS)).not.toMatch(/\.checklist-schedule-option\b/);
  });

  it('has a reduced-motion rule and no keyframe animation of its own', () => {
    expect(CSS).toMatch(/prefers-reduced-motion:\s*reduce/);
    expect(CSS).not.toMatch(/@keyframes/);
  });

  it('keeps long titles and hundreds of items workable: clamped titles, wrapped values, deferred row rendering', () => {
    expect(CSS).toMatch(/\.checklist-row__title\s*\{[^}]*line-clamp:\s*2/);
    expect(CSS).toMatch(/\.checklist-row__title\s*\{[^}]*overflow-wrap:\s*anywhere/);
    expect(CSS).toMatch(/\.checklist-window__item\s*\{[^}]*content-visibility:\s*auto/);
    expect(CSS).toMatch(/\.checklist-window__panel\s*\{[^}]*overflow-y:\s*auto/);
    expect(CSS).toMatch(/\.overlay-card\.checklist-window\s*\{[^}]*max-height:\s*92%/);
  });

  it('gives the sidebar badge a style in the row sheet without adding an inline style to the row', () => {
    expect(ROW_CSS).toMatch(/\.agent-task-row__checklist\.is-attention svg\s*\{\s*color:\s*var\(--warning-base\)/);
    expect((read('../sidebar/AgentTaskRow.tsx').match(/style=\{/g) ?? []).length).toBe(1);
  });

  it('imports the stylesheet after the overlay styles it extends', () => {
    const entry = read('../../styles/components.css');
    expect(entry).toContain("@import './components/detail-tray/checklist.css';");
    expect(entry.indexOf('checklist.css')).toBeGreaterThan(entry.indexOf('overlays-and-approvals.css'));
  });

  it('shows the short list in the Run overview and keeps nothing checklist-shaped above the follow-up box', () => {
    const tray = read('../ExecutionDetailTray.tsx');
    expect(tray).toMatch(/<div className="run-overview-body">\s*<ChecklistOverviewSection rootTaskId=\{rootTaskId\} \/>\s*\{overviewBody\}/);
    const surface = read('../../app/AgentTaskDetailSurface.tsx');
    expect(surface).not.toMatch(/ChecklistInline/);
    expect(read('./ChecklistRailPill.tsx')).toMatch(/onClick=\{\(\) => openChecklistWindow\(rootTaskId\)\}/);
    expect(stripComments(CSS)).not.toMatch(/checklist-inline/);
  });

  it('draws an opened item as one card whose row is its header, and keeps the window header to one button', () => {
    expect(stripComments(CSS)).toMatch(/\.checklist-window__item\.is-expanded\s*\{[^}]*border:\s*var\(--border-medium\) solid var\(--secondary\)/);
    expect(COMPONENTS['ChecklistWindow.tsx']).not.toMatch(/Close list|Reopen list/);
  });
});
