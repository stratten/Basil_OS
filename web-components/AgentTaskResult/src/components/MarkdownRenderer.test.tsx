// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { marked } from 'marked';
import MarkdownRenderer from './MarkdownRenderer';
import { openExternalUrl, openFile } from '../services/bridge';

vi.mock('../services/bridge', () => ({
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
