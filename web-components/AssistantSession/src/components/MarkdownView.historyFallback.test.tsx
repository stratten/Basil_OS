import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MarkdownView } from './MarkdownView';

describe('MarkdownView link routing fallbacks', () => {
  const sessionPostMessage = vi.fn();
  const historyPostMessage = vi.fn();

  beforeEach(() => {
    sessionPostMessage.mockReset();
    historyPostMessage.mockReset();
  });

  afterEach(() => {
    window.webkit = undefined;
  });

  it('falls back to the history bridge when the session bridge is not installed', () => {
    window.webkit = {
      messageHandlers: {
        assistantOutputHistoryBridge: { postMessage: historyPostMessage },
      },
    };
    render(<MarkdownView content="[Basil](https://example.com/docs)" />);
    fireEvent.click(screen.getByRole('link', { name: 'Basil' }));
    expect(historyPostMessage).toHaveBeenCalledWith({
      type: 'openHistoryExternalUrl',
      url: 'https://example.com/docs',
    });
    expect(sessionPostMessage).not.toHaveBeenCalled();
  });

  it('prefers the session bridge and does not also notify the history bridge', () => {
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage: sessionPostMessage },
        assistantOutputHistoryBridge: { postMessage: historyPostMessage },
      },
    };
    render(<MarkdownView content="[Basil](https://example.com/docs)" />);
    fireEvent.click(screen.getByRole('link', { name: 'Basil' }));
    expect(sessionPostMessage).toHaveBeenCalledTimes(1);
    expect(historyPostMessage).not.toHaveBeenCalled();
  });

  it('does not throw when no native host is present', () => {
    window.webkit = undefined;
    render(<MarkdownView content="[Basil](https://example.com/docs)" />);
    expect(() => fireEvent.click(screen.getByRole('link', { name: 'Basil' }))).not.toThrow();
  });
});
