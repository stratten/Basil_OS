import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ResourceAdvice as Advice } from './resourceAdviceTypes';

const hoisted = vi.hoisted(() => ({ advice: [] as unknown[], dismiss: vi.fn(), openAppSettings: vi.fn(), lastOptions: null as unknown }));
vi.mock('./useResourceAdvice', () => ({
  useResourceAdvice: (options: unknown) => {
    hoisted.lastOptions = options;
    return { advice: hoisted.advice, dismiss: hoisted.dismiss };
  },
}));
vi.mock('../bridge/meetingBridge', () => ({ openAppSettings: hoisted.openAppSettings }));

import ResourceAdvice from './ResourceAdvice';

const lag: Advice = { id: 'transcription_lag', severity: 'warning', title: 'Transcription is behind the meeting', detail: 'Choose a smaller transcription model in Settings.', action: 'open_settings', raised_at: Date.now() / 1000 - 300 };
const heat: Advice = { id: 'thermal', severity: 'critical', title: 'Your Mac is running hot', detail: 'Move to a cooler spot.', action: 'none', raised_at: Date.now() / 1000 - 5 };

beforeEach(() => {
  hoisted.advice = [];
  hoisted.dismiss.mockReset();
  hoisted.openAppSettings.mockReset();
});

describe('ResourceAdvice', () => {
  it('renders nothing when there is no advice', () => {
    const { container } = render(<ResourceAdvice port={8123} recording thermalState="nominal" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('passes its inputs to the hook', () => {
    render(<ResourceAdvice port={8123} recording thermalState="serious" />);
    expect(hoisted.lastOptions).toEqual({ port: 8123, recording: true, thermalState: 'serious' });
  });

  it('shows a collapsed chip with the top title and a count of the rest', () => {
    hoisted.advice = [heat, lag];
    render(<ResourceAdvice port={8123} recording />);
    const chip = screen.getByRole('button', { name: 'Your Mac is running hot and 1 more' });
    expect(chip).toHaveAttribute('aria-expanded', 'false');
    expect(chip.className).toContain('meeting-resource-chip--critical');
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('expands to show each item with how long it has lasted, and collapses again', () => {
    hoisted.advice = [heat, lag];
    render(<ResourceAdvice port={8123} recording />);
    const chip = screen.getByRole('button', { name: /Your Mac is running hot/ });
    fireEvent.click(chip);
    expect(chip).toHaveAttribute('aria-expanded', 'true');
    expect(chip).toHaveAttribute('aria-controls', screen.getByRole('list', { name: 'Recording performance advice' }).id);
    expect(screen.getByText('Move to a cooler spot.')).toBeInTheDocument();
    expect(screen.getByText('just now')).toBeInTheDocument();
    expect(screen.getByText('for 5 min')).toBeInTheDocument();
    fireEvent.click(chip);
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('offers Open Settings only on advice that has that action', () => {
    hoisted.advice = [heat, lag];
    render(<ResourceAdvice port={8123} recording />);
    fireEvent.click(screen.getByRole('button', { name: /Your Mac is running hot/ }));
    const buttons = screen.getAllByRole('button', { name: 'Open Settings' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(hoisted.openAppSettings).toHaveBeenCalledTimes(1);
  });

  it('dismisses the chosen item', () => {
    hoisted.advice = [heat, lag];
    render(<ResourceAdvice port={8123} recording />);
    fireEvent.click(screen.getByRole('button', { name: /Your Mac is running hot/ }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Dismiss' })[1]);
    expect(hoisted.dismiss).toHaveBeenCalledWith('transcription_lag');
  });

  it('closes on Escape without leaving the panel open for the next advice', () => {
    hoisted.advice = [lag];
    const { rerender } = render(<ResourceAdvice port={8123} recording />);
    fireEvent.click(screen.getByRole('button', { name: /Transcription is behind/ }));
    fireEvent.keyDown(screen.getByRole('list'), { key: 'Escape' });
    expect(screen.queryByRole('list')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Transcription is behind/ }));
    hoisted.advice = [];
    rerender(<ResourceAdvice port={8123} recording />);
    hoisted.advice = [lag];
    rerender(<ResourceAdvice port={8123} recording />);
    expect(screen.queryByRole('list')).toBeNull();
  });

  it('keeps long titles and details inside the panel instead of overflowing', () => {
    hoisted.advice = [{ ...lag, title: 'T'.repeat(300), detail: 'D'.repeat(600) }];
    render(<ResourceAdvice port={8123} recording />);
    fireEvent.click(screen.getByRole('button', { name: /TTTT/ }));
    expect(screen.getByText('D'.repeat(600))).toBeInTheDocument();
  });
});
