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

  it('places the Researched badge on its own row below the Show in transcript chip', () => {
    expect(rule('.companion-item-header > .companion-badge')).toContain('order: 6');
    const breaker = rule('.companion-item-header:has(> .companion-link-chip)::after');
    expect(breaker).toContain('flex-basis: 100%');
    expect(breaker).toContain('order: 5');
  });
});
