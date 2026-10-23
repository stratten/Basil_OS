import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../bridge/meetingBridge', () => ({
  pickCompanionFolder: vi.fn(),
  subscribeFilesDropped: vi.fn(() => () => undefined),
}));
import { pickCompanionFolder } from '../bridge/meetingBridge';
import CompanionSetupPane from './CompanionSetupPane';
import type { CompanionController } from './useCompanion';

function controller(overrides: Partial<CompanionController> = {}): CompanionController {
  return {
    pendingRoots: [],
    actionError: null,
    clearActionError: vi.fn(),
    addRoots: vi.fn(async () => undefined),
    removeRoot: vi.fn(async () => true),
    removePendingRoot: vi.fn(),
    ...overrides,
  } as unknown as CompanionController;
}

const loaded = {
  settings: {
    auto_enable: true,
    default_mode: 'active' as const,
    screen_share_note_dismissed: true,
    next_focus: '',
    proposal_mode: 'suggestion_only' as const,
    proposal_capabilities: ['todo' as const, 'agent_task' as const, 'assistant_session' as const],
    auto_execute_capabilities: [],
  },
  update: vi.fn(async () => true), refresh: vi.fn(async () => undefined) };

describe('CompanionSetupPane', () => {
  it('says the Companion starts with the next recording and lets the folder picker queue sources', () => {
    render(<CompanionSetupPane controller={controller()} globalSettings={loaded} onClose={vi.fn()} />);
    expect(screen.getByText('Ready. The Companion starts with your next recording.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Attach files or folders' }));
    expect(pickCompanionFolder).toHaveBeenCalledTimes(1);
  });

  it('lists queued sources and removes them', () => {
    const queued = controller({ pendingRoots: ['/tmp/notes'] });
    render(<CompanionSetupPane controller={queued} globalSettings={loaded} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Remove queued /tmp/notes' }));
    expect(queued.removePendingRoot).toHaveBeenCalledWith('/tmp/notes');
  });

  it('hides on request and has no mode select of its own', () => {
    const onClose = vi.fn();
    render(<CompanionSetupPane controller={controller()} globalSettings={{ settings: null, update: vi.fn(async () => false), refresh: vi.fn(async () => undefined) }} onClose={onClose} />);
    expect(screen.queryByRole('button', { name: 'Companion mode' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Hide the Companion' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('saves the focus for the next recording', () => {
    const update = vi.fn(async () => true);
    render(<CompanionSetupPane controller={controller()} globalSettings={{ ...loaded, update }} onClose={vi.fn()} />);
    const focus = screen.getByLabelText('Focus (optional):');
    fireEvent.change(focus, { target: { value: 'Pricing objections' } });
    fireEvent.blur(focus);
    expect(update).toHaveBeenCalledWith({ next_focus: 'Pricing objections' });
  });

  it('shows a queue failure with a dismiss action', () => {
    const failing = controller({ actionError: 'Could not attach /tmp/x' });
    render(<CompanionSetupPane controller={failing} globalSettings={loaded} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));
    expect(failing.clearActionError).toHaveBeenCalledTimes(1);
  });
});
