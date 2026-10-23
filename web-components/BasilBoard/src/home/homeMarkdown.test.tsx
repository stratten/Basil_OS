import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import HomeMarkdown from './HomeMarkdown';

const mocks = vi.hoisted(() => ({
  openExternalUrl: vi.fn(),
}));

vi.mock('../services/bridge', () => ({
  openExternalUrl: mocks.openExternalUrl,
}));

describe('HomeMarkdown', () => {
  it('renders bold, list, and code content safely', () => {
    render(<HomeMarkdown content={'**Bold**\n\n- one\n\n`code`'} variant="assistant" />);
    expect(document.querySelector('strong')?.textContent).toBe('Bold');
    expect(document.querySelector('li')?.textContent).toBe('one');
    expect(document.querySelector('code')?.textContent).toBe('code');
  });

  it('removes script tags and unsafe link schemes', () => {
    render(<HomeMarkdown content={'[bad](javascript:alert(1))\n\n<script>alert(1)</script>'} variant="assistant" />);
    expect(document.querySelector('script')).toBeNull();
    const anchor = document.querySelector('a');
    expect(anchor?.getAttribute('href')).toBeNull();
  });

  it('opens valid external links through the bridge', () => {
    render(<HomeMarkdown content={'[Docs](https://example.com/docs)'} variant="assistant" />);
    const anchor = screen.getByRole('link', { name: 'Docs' });
    fireEvent.click(anchor);
    expect(mocks.openExternalUrl).toHaveBeenCalledWith('https://example.com/docs');
  });

  it('escapes fallback html when parsing fails', () => {
    const view = render(<HomeMarkdown content={'<img src=x onerror=alert(1)>'} variant="assistant" />);
    const html = view.container.querySelector('.home-markdown')?.innerHTML ?? '';
    expect(view.container.querySelector('img')).toBeNull();
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('<script');
  });
});
