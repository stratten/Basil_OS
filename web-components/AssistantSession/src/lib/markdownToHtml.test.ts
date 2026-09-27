import { describe, expect, it } from 'vitest';
import { markdownToHTML } from './markdownToHtml';

describe('markdownToHTML', () => {
  it('renders the Swift-supported markdown forms', () => {
    const rendered = markdownToHTML('## Heading\n**bold** *italic* `code`');
    expect(rendered).toContain('<h2>Heading</h2>');
    expect(rendered).toContain('<strong>bold</strong> <em>italic</em> <code>code</code>');
  });

  it('renders normal MarkdownUI structures omitted by the old regex port', () => {
    const rendered = markdownToHTML('# Title\n\n- one\n- two\n\n> quoted');
    expect(rendered).toContain('<h1>Title</h1>');
    expect(rendered).toContain('<ul>');
    expect(rendered).toContain('<blockquote>');
  });

  it('escapes model-provided HTML before rendering markdown', () => {
    const rendered = markdownToHTML('<img src=x onerror="window.webkit.messageHandlers.bad.postMessage(1)">');
    expect(rendered).not.toContain('<img');
    expect(rendered).not.toContain('onerror="');
  });
});
