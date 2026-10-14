import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionScreenShareNote from './CompanionScreenShareNote';
import type { CompanionGlobalSettings } from './types';

const settings = (dismissed: boolean | undefined): CompanionGlobalSettings => ({ auto_enable: false, default_mode: 'active', next_focus: '', screen_share_note_dismissed: dismissed as boolean });

describe('CompanionScreenShareNote', () => {
  it('asks the shared settings controller to save the dismissal exactly once', () => {
    const update = vi.fn().mockResolvedValue(true);
    render(<CompanionScreenShareNote settings={settings(false)} update={update} />);
    expect(screen.getByRole('note')).toHaveTextContent('Sharing your screen? You may want to share a single window or close the companion first.');
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
    expect(update).toHaveBeenCalledTimes(1);
    expect(update).toHaveBeenCalledWith({ screen_share_note_dismissed: true });
  });

  it('explains when the dismissal cannot be saved', async () => {
    const update = vi.fn().mockResolvedValue(false);
    render(<CompanionScreenShareNote settings={settings(false)} update={update} />);
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }));
    expect(await screen.findByText('That could not be saved, so this note will appear again.')).toBeInTheDocument();
  });

  it('stays hidden once dismissed, for an older backend without the field, and while settings are unavailable', () => {
    const update = vi.fn();
    const dismissed = render(<CompanionScreenShareNote settings={settings(true)} update={update} />);
    expect(screen.queryByRole('note')).toBeNull();
    dismissed.unmount();

    const older = render(<CompanionScreenShareNote settings={settings(undefined)} update={update} />);
    expect(screen.queryByRole('note')).toBeNull();
    older.unmount();

    render(<CompanionScreenShareNote settings={null} update={update} />);
    expect(screen.queryByRole('note')).toBeNull();
  });
});
