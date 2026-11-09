// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { marked } from 'marked';
import MarkdownRenderer from './MarkdownRenderer';
import { copyToClipboard, openExternalUrl, openFile } from '../services/bridge';
import { CHECK_ICON_MARKUP, COPY_ICON_MARKUP } from './result/copyIconMarkup';

vi.mock('../services/bridge', () => ({
  copyToClipboard: vi.fn(),
  openFile: vi.fn(),
  openExternalUrl: vi.fn(),
}));

let container: HTMLElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  vi.restoreAllMocks();
  delete (window as unknown as Record<string, unknown>).__basilMarkdownProbe;
});

function render(content: string) {
  act(() => {
    root = createRoot(container);
    root.render(<MarkdownRenderer content={content} />);
  });
}

describe('MarkdownRenderer sanitization', () => {
  it('keeps ordinary markdown formatting and links', () => {
    render('**bold** and [docs](https://example.com/docs)');

    expect(container.querySelector('strong')?.textContent).toBe('bold');
    expect(container.querySelector('a')?.getAttribute('href')).toBe('https://example.com/docs');
  });

  it('removes scripts and inline event handlers from raw HTML', () => {
    render('Hello <img src="missing.png" onerror="window.__basilMarkdownProbe = 1"><script>window.__basilMarkdownProbe = 2</script>');

    expect(container.querySelector('script')).toBeNull();
    const image = container.querySelector('img');
    expect(image).not.toBeNull();
    expect(image?.getAttribute('onerror')).toBeNull();
    expect((window as unknown as Record<string, unknown>).__basilMarkdownProbe).toBeUndefined();
  });

  it('removes javascript: link targets', () => {
    render('[click me](javascript:alert(1))');

    const link = container.querySelector('a');
    expect(link?.getAttribute('href') ?? '').not.toMatch(/^javascript:/i);
  });

  it('forbids embedded frames, forms, style blocks, media, and inline styles', () => {
    render(
      '<iframe src="https://example.com"></iframe><form action="https://example.com"><input></form>'
        + '<style>body { display: none; }</style><video src="clip.mp4"></video><audio src="a.mp3"></audio>'
        + '<p style="position: fixed">styled</p>',
    );

    expect(container.querySelector('iframe')).toBeNull();
    expect(container.querySelector('form')).toBeNull();
    expect(container.querySelector('style')).toBeNull();
    expect(container.querySelector('video')).toBeNull();
    expect(container.querySelector('audio')).toBeNull();
    expect(container.querySelector('p[style]')).toBeNull();
    expect(container.textContent).toContain('styled');
  });

  it('reduces a hostile code-fence language to a safe class name', () => {
    render('```js"onmouseover="alert(1)\nconst value = 1;\n```');

    const code = container.querySelector('pre code');
    expect(code).not.toBeNull();
    expect(code?.getAttribute('onmouseover')).toBeNull();
    expect(code?.className).toMatch(/^hljs language-[A-Za-z0-9_+-]+$/);
  });

  it('escapes the fallback paragraph when markdown parsing fails', () => {
    vi.spyOn(marked, 'parse').mockImplementation(() => {
      throw new Error('parse failure');
    });

    render('<img src=x onerror="window.__basilMarkdownProbe = 3">');

    expect(container.querySelector('img')).toBeNull();
    expect(container.textContent).toContain('<img src=x');
    expect((window as unknown as Record<string, unknown>).__basilMarkdownProbe).toBeUndefined();
  });

  it('routes http links to the external opener and other links to the file opener', () => {
    render('[site](https://example.com) and [report](/tmp/report.md)');
    const [siteLink, fileLink] = Array.from(container.querySelectorAll('a'));

    act(() => {
      siteLink.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      fileLink.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });

    expect(openExternalUrl).toHaveBeenCalledWith('https://example.com');
    expect(openFile).toHaveBeenCalledWith('/tmp/report.md');
  });
});

describe('MarkdownRenderer copy buttons', () => {
  function click(element: Element) {
    act(() => {
      element.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
    });
  }

  it('gives every fenced block and quote its own copy button', () => {
    render('```\nfirst\n```\n\n> quoted line\n\n```python\nsecond = 2\n```');

    const blocks = container.querySelectorAll('.markdown-copy-block');
    expect(blocks).toHaveLength(3);
    expect(container.querySelectorAll('.markdown-copy-block > .markdown-copy-bar > .markdown-copy-button')).toHaveLength(3);
    expect(container.querySelector('.markdown-copy-block > pre code')).not.toBeNull();
    expect(container.querySelector('.markdown-copy-block > blockquote')?.textContent).toContain('quoted line');
    expect(container.textContent).toContain('python');
  });

  it('copies exactly the text of the block beside the clicked button', () => {
    render('```\nfirst line\nsecond line\n```\n\n```\nother block\n```');
    const buttons = container.querySelectorAll('.markdown-copy-button');

    click(buttons[0]);
    expect(copyToClipboard).toHaveBeenLastCalledWith('first line\nsecond line');
    click(buttons[1]);
    expect(copyToClipboard).toHaveBeenLastCalledWith('other block');
  });

  it('copies a quote without the button labels of quotes nested inside it', () => {
    render('> outer line\n>\n> > inner line');
    const [outerButton] = Array.from(container.querySelectorAll('.markdown-copy-button'));

    click(outerButton);

    const calls = vi.mocked(copyToClipboard).mock.calls;
    const copied = calls[calls.length - 1]?.[0] ?? '';
    expect(copied).toContain('outer line');
    expect(copied).toContain('inner line');
    expect(copied).not.toContain('Copy');
    expect(copied).not.toContain('Quote');
  });

  it('uses the copy icon the rest of the result area uses, with no text on the button', () => {
    render('```\nvalue\n```\n\n> quoted');

    const buttons = Array.from(container.querySelectorAll<HTMLElement>('.markdown-copy-button'));
    expect(buttons).toHaveLength(2);
    for (const button of buttons) {
      expect(button.textContent).toBe('');
      expect(button.querySelector('svg rect')).not.toBeNull();
      expect(button.innerHTML).toBe(COPY_ICON_MARKUP);
    }
    expect(buttons[0].getAttribute('aria-label')).toBe('Copy code');
    expect(buttons[1].getAttribute('aria-label')).toBe('Copy quote');
  });

  it('confirms the copy with the check mark and then restores the icon and label', () => {
    vi.useFakeTimers();
    try {
      render('```\nvalue\n```');
      const button = container.querySelector('.markdown-copy-button') as HTMLElement;

      click(button);
      expect(button.innerHTML).toBe(CHECK_ICON_MARKUP);
      expect(button.getAttribute('aria-label')).toBe('Copy code copied');
      expect(button.title).toBe('Copy code copied');
      act(() => {
        vi.advanceTimersByTime(2000);
      });
      expect(button.innerHTML).toBe(COPY_ICON_MARKUP);
      expect(button.getAttribute('aria-label')).toBe('Copy code');
      expect(button.title).toBe('Copy code');
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not open links or copy anything when other content is clicked', () => {
    render('```\nvalue\n```');

    click(container.querySelector('pre') as Element);

    expect(copyToClipboard).not.toHaveBeenCalled();
    expect(openFile).not.toHaveBeenCalled();
  });
});
