import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import ScheduledChainField from './ScheduledChainField';
import ScheduledExclusionWindowsField from './ScheduledExclusionWindowsField';
import { DEFAULT_CHAIN_FORM } from './scheduledChainHelpers';

describe('ScheduledChainField', () => {
  it('shows only the mode picker while runs are independent', () => {
    const markup = renderToStaticMarkup(<ScheduledChainField form={DEFAULT_CHAIN_FORM} onChange={vi.fn()} />);
    expect(markup).toContain('Each run is its own task');
    expect(markup).not.toContain('Start a new conversation after');
  });

  it('shows both limits, the carry-over switch, and no error for a valid chained form', () => {
    const markup = renderToStaticMarkup(<ScheduledChainField form={{ ...DEFAULT_CHAIN_FORM, chained: true }} onChange={vi.fn()} />);
    expect(markup).toContain('Runs continue one conversation');
    expect(markup).toContain('Start a new conversation after');
    expect(markup).toContain('aria-label="Maximum runs in one conversation"');
    expect(markup).toContain('aria-label="Maximum conversation length"');
    expect(markup).toContain('aria-label="Carry the last result over to the new conversation"');
    expect(markup).not.toContain('role="alert"');
  });

  it('shows an alert when a chained form has no limit', () => {
    const markup = renderToStaticMarkup(<ScheduledChainField form={{ ...DEFAULT_CHAIN_FORM, chained: true, limitRuns: false, limitAge: false }} onChange={vi.fn()} />);
    expect(markup).toContain('role="alert"');
    expect(markup).toContain('Choose a run limit, a time limit, or both');
  });
});

describe('ScheduledExclusionWindowsField', () => {
  it('offers only the add button when there are no windows', () => {
    const markup = renderToStaticMarkup(<ScheduledExclusionWindowsField windows={[]} onChange={vi.fn()} />);
    expect(markup).toContain('Quiet hours');
    expect(markup).toContain('Add quiet hours');
    expect(markup).not.toContain('Do not run from');
  });

  it('renders one group per window with times, weekday toggles, and a remove button', () => {
    const markup = renderToStaticMarkup(
      <ScheduledExclusionWindowsField windows={[{ start: '22:00', end: '07:00', days: [5] }, { start: '12:00', end: '13:00', days: [] }]} onChange={vi.fn()} />,
    );
    expect(markup).toContain('aria-label="Quiet hours window 1"');
    expect(markup).toContain('aria-label="Quiet hours window 2"');
    expect(markup).toContain('value="22:00"');
    expect(markup).toContain('value="07:00"');
    expect(markup).toContain('aria-pressed="true" aria-label="Sat for quiet hours window 1"');
    expect(markup).toContain('Starting on the selected days only.');
    expect(markup).toContain('Every day.');
    expect(markup).toContain('Remove quiet hours window 2');
  });

  it('disables the add button at eight windows and alerts on an invalid window', () => {
    const eight = Array.from({ length: 8 }, () => ({ start: '01:00', end: '02:00', days: [] as number[] }));
    expect(renderToStaticMarkup(<ScheduledExclusionWindowsField windows={eight} onChange={vi.fn()} />)).toMatch(/<button[^>]*disabled=""[^>]*>Add quiet hours<\/button>/);
    const invalid = renderToStaticMarkup(<ScheduledExclusionWindowsField windows={[{ start: '00:00', end: '00:00', days: [] }]} onChange={vi.fn()} />);
    expect(invalid).toContain('role="alert"');
    expect(invalid).toContain('choose the weekdays it applies to');
  });
});
