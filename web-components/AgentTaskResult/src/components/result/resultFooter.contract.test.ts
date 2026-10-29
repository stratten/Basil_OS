import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(__dirname, '../../styles/components/result-content.css'), 'utf8');

function rule(selector: string): string {
  const match = css.match(new RegExp(`${selector.replace(/[.]/g, '\\.')}\\s*\\{([^}]*)\\}`));
  expect(match, `${selector} rule`).not.toBeNull();
  return match?.[1] ?? '';
}

describe('result footer styling', () => {
  it('is a minimal single row that mirrors the conversation message footer', () => {
    const footer = rule('.result-footer');
    expect(footer).toContain('display: flex');
    expect(footer).toContain('gap: 6px');
    expect(footer).toContain('min-height: 20px');
    expect(footer).toContain('padding: 0 2px');
    expect(footer).toContain('font-size: calc(10px * var(--text-scale, 1))');
    expect(footer).toContain('color-mix(in srgb, var(--text-primary) 62%, transparent)');
  });

  it('renders the model name slightly less opaque than the time', () => {
    expect(rule('.result-footer__model')).toContain('color-mix(in srgb, var(--text-primary) 50%, transparent)');
  });

  it('no longer styles the old pill beside the Result heading', () => {
    expect(css).not.toContain('.result-model-label');
  });
});
