import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { initialAssistantSessionState } from '../../state/assistantSessionReducer';
import { ResultState } from '../ResultState';
import { pasteStatusText } from './PasteStatusLine';

describe('pasteStatusText', () => {
  it.each([
    ['pasted', 'Mail', 'Pasted into Mail'],
    ['pasted', null, 'Pasted'],
    ['shown', 'Mail', 'Not pasted (shown here)'],
    ['switchedApps', 'Mail', 'Not pasted (you left Mail)'],
    ['switchedApps', null, 'Not pasted (you switched apps)'],
    ['targetUnavailable', 'Mail', "Not pasted (couldn't return to Mail)"],
    ['targetUnavailable', null, 'Not pasted (no app to paste into)'],
  ] as const)('%s with %s reads %s', (outcome, applicationName, expected) => {
    expect(pasteStatusText(outcome, applicationName)).toBe(expected);
  });
});

describe('ResultState paste status line', () => {
  const completed = {
    ...initialAssistantSessionState,
    assistantSessionStatus: 'completed' as const,
    assistantOutput: 'Draft reply',
    shouldPersistUI: true,
  };

  beforeEach(() => {
    window.webkit = { messageHandlers: { assistantSessionBridge: { postMessage: vi.fn() } } };
  });

  it('names the app a completed response was pasted into', () => {
    render(<ResultState state={{ ...completed, pasteOutcome: 'pasted', pasteTargetApplicationName: 'Mail' }} />);
    expect(screen.getByText('Pasted into Mail')).toBeInTheDocument();
  });

  it('explains why a response was kept in the widget', () => {
    render(<ResultState state={{ ...completed, pasteOutcome: 'shown', pasteTargetApplicationName: 'Safari' }} />);
    expect(screen.getByText('Not pasted (shown here)')).toBeInTheDocument();
  });

  it('renders no status line when no paste was attempted', () => {
    const { container } = render(<ResultState state={completed} />);
    expect(container.querySelector('.assistant-session-result__paste-status')).toBeNull();
  });

  it('hides the status line while a new response is running', () => {
    render(<ResultState state={{ ...completed, assistantSessionStatus: 'running', pasteOutcome: 'pasted', pasteTargetApplicationName: 'Mail' }} />);
    expect(screen.queryByText('Pasted into Mail')).not.toBeInTheDocument();
  });

  it('keeps a long application name on one readable line', () => {
    const longName = 'An Extremely Long Application Name That Keeps Going For Testing';
    render(<ResultState state={{ ...completed, pasteOutcome: 'switchedApps', pasteTargetApplicationName: longName }} />);
    expect(screen.getByText(`Not pasted (you left ${longName})`)).toBeInTheDocument();
  });
});
