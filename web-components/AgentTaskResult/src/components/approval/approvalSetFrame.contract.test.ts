// @vitest-environment node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');
const stripComments = (source: string) => source.replace(/\/\*[\s\S]*?\*\//g, '');

const CSS = stripComments(read('../../styles/components/overlays-and-approvals.css'));
const COMPONENT = read('ApprovalSetOverlay.tsx');

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, '\\$&');
  const match = CSS.match(new RegExp(`(?:^|\\})\\s*${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`No rule for ${selector}`);
  return match[1];
}

describe('the stacked approval card keeps its button row outside the scrolling area', () => {
  it('makes the card a frame that never scrolls, so nothing can sit behind the row', () => {
    const frame = rule('.overlay-card.approval-set-frame');
    expect(frame).toMatch(/display:\s*flex/);
    expect(frame).toMatch(/flex-direction:\s*column/);
    expect(frame).toMatch(/max-height:\s*82vh/);
    expect(frame).toMatch(/overflow:\s*hidden/);
    expect(frame).not.toMatch(/overflow-y:\s*auto/);
  });

  it('scrolls only the list between the title and the row', () => {
    const scroller = rule('.approval-set-scroller');
    expect(scroller).toMatch(/overflow-y:\s*auto/);
    expect(scroller).toMatch(/min-height:\s*0/);
    expect(scroller).toMatch(/flex:\s*1 1 auto/);
  });

  it('holds the row in place by layout rather than by sticky positioning', () => {
    const footer = rule('.approval-set-footer');
    expect(footer).toMatch(/flex:\s*0 0 auto/);
    expect(footer).not.toMatch(/position:\s*sticky/);
  });

  it('keeps the layout out of inline styles on the frame and the list', () => {
    const start = COMPONENT.indexOf('approval-set-frame');
    const end = COMPONENT.indexOf('<DecisionActions className="approval-set-footer">');
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    expect(COMPONENT.slice(start, end)).not.toContain('style=');
  });
});
