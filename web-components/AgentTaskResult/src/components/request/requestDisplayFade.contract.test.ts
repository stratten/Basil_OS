import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(__dirname, '../../styles/components/request-display.css'), 'utf8');

function rule(selector: string): string {
  const escaped = selector.replace(/[.:()-]/g, character => `\\${character}`);
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match ? match[1] : '';
}

describe('request display fade', () => {
  it('fades the clipped request with a vertical mask only while it is collapsed and overflowing', () => {
    const collapsed = rule('.request-display-content.has-overflow:not(.is-expanded)');
    expect(collapsed).toContain('mask-image: linear-gradient(to bottom, #000 calc(100% - var(--request-display-fade)), transparent)');
    expect(collapsed).toContain('-webkit-mask-image: linear-gradient(to bottom');
  });

  it('does not mask the expanded request or fake the fade with a background-colored overlay', () => {
    expect(rule('.request-display-content.is-expanded')).not.toContain('mask-image');
    expect(css).not.toContain('::after');
  });
});
