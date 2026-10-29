import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const stylesRoot = resolve(__dirname);
const read = (relative: string) => readFileSync(resolve(stylesRoot, relative), 'utf8');

describe('search highlight styles', () => {
  it('no longer paints the generic yellow highlight', () => {
    expect(read('components/result-content.css')).not.toMatch(/#ffe14d|::highlight\(search-match\)/i);
  });

  it('loads the shared Companion-style section highlight, tint and flash', () => {
    const shared = read('../../../shared/search/search-highlight.css');
    expect(shared).toContain('search-section-flash');
    expect(shared).toContain('::highlight(search-match)');
    expect(shared).toContain('background-color: color-mix(in srgb, var(--secondary) 34%, transparent);');
    expect(shared).toContain('text-decoration-color: var(--secondary);');
    expect(shared).toContain('text-decoration-thickness: 2px;');
    expect(shared).toContain('[data-search-section="jump"]::after');
    expect(shared).toContain('prefers-reduced-motion');
    expect(shared).not.toMatch(/#ffe14d/i);
    expect(read('components.css')).toContain("@import '../../../shared/search/search-highlight.css';");
  });
});
