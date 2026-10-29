import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const css = readFileSync('src/styles/companion.css', 'utf8');

function rule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, '\\$&');
  const match = new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  expect(match, `missing ${selector} rule`).not.toBeNull();
  return match![1];
}

describe('Companion card header layout', () => {
  it('wraps instead of overflowing and reserves room for the pinned dismiss button', () => {
    const header = rule('.companion-item-header');
    expect(header).toContain('flex-wrap: wrap');
    expect(header).toContain('padding-right: 28px');
    const dismiss = rule('.companion-item-header .companion-item-dismiss');
    expect(dismiss).toContain('position: absolute');
    expect(dismiss).toContain('right: 0');
  });

  it('no longer lays the Researched badge out inside the header', () => {
    expect(css).not.toContain('.companion-item-header > .companion-badge');
    expect(css).not.toContain('.companion-item-header:has(> .companion-link-chip)::after');
  });

  it('puts the Researched badge at the right end of the sources row', () => {
    const row = rule('.companion-item-evidence');
    expect(row).toContain('display: flex');
    expect(row).toContain('justify-content: space-between');
    expect(rule('.companion-item-evidence > .companion-badge')).toContain('margin-left: auto');
    expect(rule('.companion-item-evidence > .companion-citations')).toContain('flex: 1 1 auto');
  });

  it('truncates a folded note to a single line', () => {
    const preview = rule('.companion-item-preview');
    expect(preview).toContain('white-space: nowrap');
    expect(preview).toContain('text-overflow: ellipsis');
    expect(preview).toContain('overflow: hidden');
  });
});
