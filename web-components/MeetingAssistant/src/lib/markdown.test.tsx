// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MeetingMarkdown } from './markdown';

afterEach(() => {
  window.webkit = undefined;
  vi.restoreAllMocks();
});

function installBridge() {
  const postMessage = vi.fn();
  window.webkit = { messageHandlers: { meetingBridge: { postMessage } } };
  return postMessage;
}

describe('MeetingMarkdown', () => {
  it('removes executable link protocols while retaining safe links', () => {
    render(<MeetingMarkdown content={'[unsafe](javascript:alert(1)) [safe](https://example.com)'} />);
    expect(screen.getByText('unsafe')).not.toHaveAttribute('href');
    expect(screen.getByText('safe')).toHaveAttribute('href', 'https://example.com');
  });

  it('opens an https link through the bridge instead of navigating the web view', () => {
    const postMessage = installBridge();
    render(<MeetingMarkdown content={'[safe](https://example.com/path?a=1)'} />);
    const notPrevented = fireEvent.click(screen.getByText('safe'));
    expect(notPrevented).toBe(false);
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([
      { type: 'openExternalUrl', url: 'https://example.com/path?a=1' },
    ]);
  });

  it('opens a mailto link through the bridge', () => {
    const postMessage = installBridge();
    render(<MeetingMarkdown content={'[mail](mailto:someone@example.com)'} />);
    fireEvent.click(screen.getByText('mail'));
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([
      { type: 'openExternalUrl', url: 'mailto:someone@example.com' },
    ]);
  });

  it('posts nothing for a link whose unsafe protocol was stripped', () => {
    const postMessage = installBridge();
    render(<MeetingMarkdown content={'[unsafe](javascript:alert(1))'} />);
    fireEvent.click(screen.getByText('unsafe'));
    expect(postMessage).not.toHaveBeenCalled();
  });

  it('posts nothing when text outside a link is clicked', () => {
    const postMessage = installBridge();
    render(<MeetingMarkdown content={'plain text and [a link](https://example.com)'} />);
    fireEvent.click(screen.getByText(/plain text and/));
    expect(postMessage).not.toHaveBeenCalled();
  });

  it('opens the link when a nested element inside the anchor is clicked', () => {
    const postMessage = installBridge();
    render(<MeetingMarkdown content={'[**bold link**](https://example.com/bold)'} />);
    fireEvent.click(screen.getByText('bold link'));
    expect(postMessage.mock.calls.map((call) => call[0])).toEqual([
      { type: 'openExternalUrl', url: 'https://example.com/bold' },
    ]);
  });
});
