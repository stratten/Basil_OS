// @vitest-environment node
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), 'utf8');

describe('search highlight styles', () => {
  const resultCss = read('../../styles/components/result-content.css');
  const entryCss = read('../../styles/components.css');
  const highlightCss = read('../../../../shared/search/search-highlight.css');

  it('no longer paints the generic yellow highlight', () => {
    expect(resultCss.toLowerCase()).not.toContain('#ffe14d');
    expect(resultCss).not.toContain('::highlight(search-match)');
    expect(highlightCss.toLowerCase()).not.toContain('#ffe14d');
  });

  it('marks words with the secondary tint and underline and uses the Companion linked-section look with a one-time flash', () => {
    expect(highlightCss).toContain('background-color: color-mix(in srgb, var(--secondary) 34%, transparent);');
    expect(highlightCss).toContain('text-decoration-color: var(--secondary);');
    expect(highlightCss).toContain('outline: 1px solid var(--secondary)');
    expect(highlightCss).toContain('color-mix(in srgb, var(--secondary) 14%, transparent)');
    expect(highlightCss).toContain('color-mix(in srgb, var(--secondary) 34%, transparent)');
    expect(highlightCss).toContain('search-section-flash');
    expect(highlightCss).toContain('@media (prefers-reduced-motion: reduce)');
  });

  it('is imported by the Agent Task entry stylesheet', () => {
    expect(entryCss).toContain("@import '../../../shared/search/search-highlight.css';");
  });
});
