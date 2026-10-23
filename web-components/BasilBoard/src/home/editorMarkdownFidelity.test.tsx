import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { editorHtmlToDisplayMarkdown, plainTextToDisplayMarkdown } from '../../../shared/editorMarkdown';
import HomeMarkdown from './HomeMarkdown';

vi.mock('../services/bridge', () => ({ openExternalUrl: vi.fn() }));

function convert(html: string): string {
  const editor = document.createElement('div');
  editor.innerHTML = html;
  return editorHtmlToDisplayMarkdown(editor);
}

describe('editorHtmlToDisplayMarkdown fidelity', () => {
  it('joins composer lines with single newlines and keeps blank lines', () => {
    expect(convert('First<div>Second</div><div><br></div><div>Fourth</div>')).toBe('First\nSecond\n\nFourth');
  });

  it('converts headings, quotes, rules, and paragraphs', () => {
    expect(convert('<h2>Plan</h2><blockquote>Quoted <b>text</b></blockquote><hr><p>After</p>'))
      .toBe('## Plan\n\n> Quoted **text**\n\n---\n\nAfter');
  });

  it('keeps safe links and drops unsafe link targets', () => {
    expect(convert('<a href="https://example.com/a b">Docs</a> and <a href="javascript:alert(1)">bad</a>'))
      .toBe('[Docs](https://example.com/a%20b) and bad');
  });

  it('honors inline styles from pasted documents without treating a normal-weight wrapper as bold', () => {
    const pasted = '<b style="font-weight:normal" id="docs-internal-guid-1">'
      + '<span style="font-weight:700">Bold</span> '
      + '<span style="font-style:italic">it</span> '
      + '<span style="text-decoration:line-through">gone</span> '
      + '<span style="font-family:Menlo">x_y</span>'
      + '</b>';
    expect(convert(pasted)).toBe('**Bold** *it* ~~gone~~ `x_y`');
  });

  it('does not double markers for nested bold', () => {
    expect(convert('<b>a <span style="font-weight:700">b</span></b>')).toBe('**a b**');
  });

  it('converts tables with a header row and escaped pipes', () => {
    expect(convert('<table><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody><tr><td>a|b</td><td>2</td></tr></tbody></table>'))
      .toBe('| Name | Value |\n| --- | --- |\n| a\\|b | 2 |');
  });

  it('escapes typed Markdown syntax at the start of a line', () => {
    expect(convert('<div># not a heading</div><div>1. not a list</div><div>- dash</div>'))
      .toBe('\\# not a heading\n1\\. not a list\n\\- dash');
  });

  it('keeps code literal, with line breaks in code blocks and adaptive inline fences', () => {
    expect(convert('<pre>line 1<br>line 2</pre><div>Use <code>a`b</code> and <code>C:\\path\\*</code></div>'))
      .toBe('```\nline 1\nline 2\n```\n\nUse ``a`b`` and `C:\\path\\*`');
  });

  it('ignores whitespace-only formatting text between pasted blocks', () => {
    expect(convert('<p>One</p>\n  <p>Two</p>\n')).toBe('One\n\nTwo');
  });

  it('escapes literal Markdown characters in voice transcripts', () => {
    expect(plainTextToDisplayMarkdown('a*b_c~d|e')).toBe('a\\*b\\_c\\~d\\|e');
  });
});

describe('composer Markdown renders faithfully in a bubble', () => {
  it('renders headings, quotes, rules, strikethrough, and tables', () => {
    const markdown = convert(
      '<h2>Plan</h2><blockquote>Quoted</blockquote><hr><div><s>old</s> new</div>'
      + '<table><tr><th>Name</th><th>Value</th></tr><tr><td>a|b</td><td>2</td></tr></table>',
    );
    const { container } = render(<HomeMarkdown content={markdown} variant="user" />);
    expect(container.querySelector('h2')?.textContent).toBe('Plan');
    expect(container.querySelector('blockquote')?.textContent?.trim()).toBe('Quoted');
    expect(container.querySelector('hr')).not.toBeNull();
    expect(container.querySelector('del')?.textContent).toBe('old');
    expect(container.querySelector('th')?.textContent).toBe('Name');
    expect(container.querySelector('td')?.textContent).toBe('a|b');
    expect(container.querySelector('td')?.getAttribute('align')).toBeNull();
  });

  it('shows typed Markdown characters literally', () => {
    const markdown = convert('<div># not a heading</div><div>2 * 3 = 6</div>');
    const { container } = render(<HomeMarkdown content={markdown} variant="user" />);
    expect(container.querySelector('h1')).toBeNull();
    expect(container.textContent).toContain('# not a heading');
    expect(container.textContent).toContain('2 * 3 = 6');
  });
});
