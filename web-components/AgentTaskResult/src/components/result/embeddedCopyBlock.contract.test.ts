import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(__dirname, '../../styles/components/result-content.css'), 'utf8');
const copyButtons = readFileSync(join(__dirname, 'CopyButtons.tsx'), 'utf8');

function rule(selector: string): string {
  const escaped = selector.replace(/[.>:()-]/g, character => `\\${character}`);
  const match = css.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match ? match[1] : '';
}

describe('embedded code and quote blocks', () => {
  it('tint the whole block, with the bar a step stronger, instead of using the plain window background for the bar', () => {
    const block = rule('.result-section .markdown-copy-block');
    const bar = rule('.result-section .markdown-copy-bar');

    expect(block).toContain('background: color-mix(in srgb, var(--text-primary) 5%, transparent)');
    expect(bar).toContain('background: color-mix(in srgb, var(--text-primary) 5%, transparent)');
    expect(bar).not.toContain('var(--background-primary)');
    expect(rule('.result-section .markdown-copy-block > pre')).toContain('background: transparent');
  });

  it('use a borderless 20 pixel icon button like the other copy buttons, not a text button', () => {
    const button = rule('.result-section .markdown-copy-button');

    expect(button).toContain('width: 20px');
    expect(button).toContain('height: 20px');
    expect(button).toContain('border: none');
    expect(button).toContain('color: var(--secondary)');
    expect(button).not.toContain('font-family');
  });
});

describe('result copy buttons', () => {
  it('sit in the heading row rather than floating over the result text, and rest more opaque than before', () => {
    expect(copyButtons).not.toContain("position: 'absolute'");
    expect(copyButtons).toContain("marginLeft: 'auto'");
    expect(copyButtons).toContain('RESTING_OPACITY = 0.75');
    expect(copyButtons).not.toContain('0.4');
  });
});
