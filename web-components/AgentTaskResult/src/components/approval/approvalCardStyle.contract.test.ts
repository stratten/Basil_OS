// @vitest-environment node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');

const APPROVAL_CSS = read('../../styles/components/approval-details.css');
const OVERLAY_CSS = read('../../styles/components/overlays-and-approvals.css');
const HISTORY_CSS = read('../../styles/components/interaction-exchange.css');

function rule(css: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>:]/g, '\\$&');
  const match = css.match(new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`No rule for ${selector}`);
  return match[1];
}

const declaration = (block: string, property: string) => block.match(new RegExp(`${property}:\\s*([^;]+);`))?.[1].trim();

describe('the approval card matches the conversation card it later becomes', () => {
  it('gives the approval command box the same background and text color as the history command box', () => {
    const history = rule(HISTORY_CSS, '.interaction-exchange-command');
    const approval = rule(APPROVAL_CSS, '.command-display.approval-command-display');

    expect(declaration(approval, 'background')).toBe(declaration(history, 'background'));
    expect(declaration(approval, 'background')).toContain('var(--secondary)');
    expect(declaration(approval, 'color')).toBe(declaration(history, 'color'));
  });

  it('lays the title and the risk badge out as one row, badge at the right', () => {
    const row = rule(OVERLAY_CSS, '.overlay-title.overlay-title--with-badge');
    expect(row).toMatch(/display:\s*flex/);
    expect(row).toMatch(/justify-content:\s*space-between/);
    expect(rule(OVERLAY_CSS, '.overlay-title--with-badge > .risk-badge')).toMatch(/flex:\s*0 0 auto/);
  });

  it('keeps the note toggle tight against the note it opens', () => {
    const toggle = rule(APPROVAL_CSS, '.approval-link-button.approval-note-toggle');
    expect(declaration(toggle, 'padding-top')).toBe('0');
    expect(declaration(toggle, 'padding-bottom')).toBe('0');
  });
});
