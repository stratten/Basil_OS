import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TranscriptBody } from './TranscriptBody';
import * as bridge from '../bridge/transcriptionWidgetBridge';

vi.mock('../bridge/transcriptionWidgetBridge', () => ({
  copyToClipboard: vi.fn(),
}));

describe('TranscriptBody', () => {
  it('hides the copy button for status messages', () => {
    render(<TranscriptBody displayText="Ready to record" isStatus />);
    expect(screen.queryByRole('button', { name: /copy all/i })).not.toBeInTheDocument();
  });

  it('hides the copy button for empty text', () => {
    render(<TranscriptBody displayText="" isStatus={false} />);
    expect(screen.queryByRole('button', { name: /copy all/i })).not.toBeInTheDocument();
  });

  it('shows the copy button for real transcript content', () => {
    render(<TranscriptBody displayText="hello world" isStatus={false} />);
    expect(screen.getByRole('button', { name: /copy all/i })).toBeInTheDocument();
  });

  it('copies to clipboard and shows transient feedback on click', async () => {
    render(<TranscriptBody displayText="hello world" isStatus={false} />);
    await userEvent.click(screen.getByRole('button', { name: /copy all/i }));
    expect(bridge.copyToClipboard).toHaveBeenCalledOnce();
    expect(screen.getByText('Copied')).toBeInTheDocument();
  });
});
