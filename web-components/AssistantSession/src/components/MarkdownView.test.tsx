import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MarkdownView } from './MarkdownView';

describe('MarkdownView', () => {
  const postMessage = vi.fn();

  beforeEach(() => {
    postMessage.mockReset();
    window.webkit = {
      messageHandlers: {
        assistantSessionBridge: { postMessage },
      },
    };
  });

  it('routes web links through the validated native bridge', () => {
    render(<MarkdownView content="[Basil](https://example.com/docs)" />);
    fireEvent.click(screen.getByRole('link', { name: 'Basil' }));
    expect(postMessage).toHaveBeenCalledWith({
      type: 'openExternalUrl',
      url: 'https://example.com/docs',
    });
  });

  it('does not route unsupported URL schemes', () => {
    render(<MarkdownView content="[Unsafe](javascript:alert(1))" />);
    expect(screen.queryByRole('link', { name: 'Unsafe' })).not.toBeInTheDocument();
    expect(postMessage).not.toHaveBeenCalled();
  });
});
