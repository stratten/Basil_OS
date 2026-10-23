import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MarkdownView } from './MarkdownView';

const markdownToHTMLMock = vi.hoisted(() => vi.fn((markdown: string) => `<p>${markdown}</p>`));
vi.mock('../lib/markdownToHtml', () => ({ markdownToHTML: markdownToHTMLMock }));

describe('MarkdownView memoization', () => {
  it('does not re-parse markdown when content is unchanged across re-renders', () => {
    markdownToHTMLMock.mockClear();
    const { rerender } = render(<MarkdownView content="Hello world" />);
    expect(markdownToHTMLMock).toHaveBeenCalledTimes(1);

    rerender(<MarkdownView content="Hello world" className="changed-only" />);
    expect(markdownToHTMLMock).toHaveBeenCalledTimes(1);
  });

  it('re-parses markdown when content actually changes', () => {
    markdownToHTMLMock.mockClear();
    const { rerender } = render(<MarkdownView content="First" />);
    expect(markdownToHTMLMock).toHaveBeenCalledTimes(1);

    rerender(<MarkdownView content="Second" />);
    expect(markdownToHTMLMock).toHaveBeenCalledTimes(2);
  });
});
