import { describe, expect, it } from 'vitest';
import { plainMarkdownText } from './plainMarkdownText';

describe('plainMarkdownText', () => {
  it('returns an empty string for missing or syntax-only input', () => {
    expect(plainMarkdownText(undefined)).toBe('');
    expect(plainMarkdownText(null)).toBe('');
    expect(plainMarkdownText('')).toBe('');
    expect(plainMarkdownText('## ')).toBe('');
    expect(plainMarkdownText('---')).toBe('');
  });

  it('removes emphasis, headings, links, and images', () => {
    expect(plainMarkdownText('## **Large Folder** _Size_ ~~Old~~ *Investigation*')).toBe('Large Folder Size Old Investigation');
    expect(plainMarkdownText('See [the report](https://example.com/a_b) and ![chart](c.png)')).toBe('See the report and chart');
  });

  it('removes list, quote, numbered, and task prefixes from every line', () => {
    expect(plainMarkdownText('> - [x] Ship it\n2. Review\n+ Merge')).toBe('Ship it Review Merge');
  });

  it('keeps underscores and asterisks that are part of words or code', () => {
    expect(plainMarkdownText('Rename notes_v2.md for baz_qux')).toBe('Rename notes_v2.md for baz_qux');
    expect(plainMarkdownText('Run `a*b*c` on `snake_case_name`')).toBe('Run a*b*c on snake_case_name');
    expect(plainMarkdownText('Compute 2 * 3 * 4')).toBe('Compute 2 * 3 * 4');
  });

  it('drops fenced code markers but keeps their content', () => {
    expect(plainMarkdownText('Result:\n```python\nprint(1)\n```')).toBe('Result: print(1)');
  });

  it('removes unpaired markers left by server-side truncation', () => {
    expect(plainMarkdownText('**Subject: Quarterly upd...')).toBe('Subject: Quarterly upd...');
    expect(plainMarkdownText('Use the `config_pat...')).toBe('Use the config_pat...');
  });

  it('keeps escaped characters literally and strips inline HTML tags', () => {
    expect(plainMarkdownText('Price \\*not\\* bold<br>next')).toBe('Price *not* bold next');
  });
});
