import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync('src/styles/todos.css', 'utf8');
const STATUSES = ['candidate', 'open', 'in_progress', 'ready_for_review', 'completed', 'dismissed', 'canceled'] as const;

function paletteRule(status: string): string {
  const pattern = new RegExp(`\\.todo-status--${status},[^{]*\\{([^}]*)\\}`);
  const match = pattern.exec(css);
  expect(match, `missing palette rule for ${status}`).not.toBeNull();
  return match![1];
}

describe('To-Do status color palette', () => {
  it('defines a status color for every status across the list chip, detail trigger, and menu option', () => {
    for (const status of STATUSES) {
      const selectorBlock = new RegExp(`(\\.todo-status--${status},[^{]*)\\{`).exec(css)?.[1] ?? '';
      expect(selectorBlock, status).toContain(`.tokenized-select__trigger.todo-detail-status[data-value="${status}"]`);
      expect(selectorBlock, status).toContain(`.todo-detail-status-menu .tokenized-select__option[data-value="${status}"]`);
      expect(paletteRule(status), status).toMatch(/--todo-status: var\(--[a-z-]+/);
    }
  });

  it('uses the semantic state tokens the rest of the Board uses', () => {
    expect(paletteRule('candidate')).toContain('var(--notice-base');
    expect(paletteRule('open')).toContain('var(--primary)');
    expect(paletteRule('in_progress')).toContain('var(--processing-base');
    expect(paletteRule('ready_for_review')).toContain('var(--warning-base');
    expect(paletteRule('completed')).toContain('var(--success-base');
    expect(paletteRule('canceled')).toContain('var(--error-base');
  });

  it('keeps dismissed neutral and still visibly bordered rather than gray-on-gray', () => {
    expect(paletteRule('dismissed')).toContain('var(--text-secondary)');
    const chip = /\.todo-list-item-status\.todo-status \{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(chip).toMatch(/border: 1px solid color-mix\(in srgb, var\(--todo-status\)/);
    expect(chip).toContain('color-mix(in srgb, var(--todo-status) 60%, var(--text-primary))');
  });

  it('keeps the chip legible on the selected row and gives the trigger a status border and fill', () => {
    const viewing = /\.todo-list-item--viewing \.todo-list-item-status\.todo-status \{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(viewing).toContain('background: var(--background-primary)');
    const trigger = /\.tokenized-select__trigger\.todo-detail-status\[data-value\] \{([^}]*)\}/.exec(css)?.[1] ?? '';
    expect(trigger).toContain('var(--todo-status)');
    expect(trigger).toContain('border: 1px solid');
  });

  it('uses no black or white literals in the status palette', () => {
    const start = css.indexOf('/* Per-status palette.');
    const end = css.indexOf('.todo-detail-pane--empty');
    const block = css.slice(start, end);
    expect(block).not.toMatch(/#(?:000|fff)(?:[0-9a-f]{3})?\b|\b(?:black|white)\b|rgba?\(\s*(?:0\s*,\s*0\s*,\s*0|255\s*,\s*255\s*,\s*255)/i);
  });
});
