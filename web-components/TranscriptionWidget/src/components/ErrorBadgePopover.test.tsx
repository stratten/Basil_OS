import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ErrorBadgePopover } from './ErrorBadgePopover';
import * as bridge from '../bridge/transcriptionWidgetBridge';

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  showTranscriptionError: vi.fn(),
}));

describe('ErrorBadgePopover', () => {
  it('renders nothing when there is no error', () => {
    const { container } = render(<ErrorBadgePopover error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('asks the native host to show the error popover on click', async () => {
    render(<ErrorBadgePopover error="Microphone access denied" />);
    await userEvent.click(screen.getByRole('button', { name: /transcription failed/i }));
    expect(bridge.showTranscriptionError).toHaveBeenCalledOnce();
  });

  it('removes the badge when the error clears on rerender', async () => {
    const { rerender } = render(<ErrorBadgePopover error="Microphone access denied" />);
    rerender(<ErrorBadgePopover error={null} />);
    expect(screen.queryByRole('button', { name: /transcription failed/i })).not.toBeInTheDocument();
  });
});
