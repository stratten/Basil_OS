import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import AgentTasksHostPlaceholder from './AgentTasksHostPlaceholder';
import { enqueueBoardAgentTasksAvailabilityChanged } from '../services/bridge';

const mocks = vi.hoisted(() => ({
  activateBoardAgentTasksSurface: vi.fn(),
  deactivateBoardAgentTasksSurface: vi.fn(),
  postMessage: vi.fn(),
}));

vi.mock('../services/bridge', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../services/bridge')>();
  return {
    ...actual,
    activateBoardAgentTasksSurface: mocks.activateBoardAgentTasksSurface,
    deactivateBoardAgentTasksSurface: mocks.deactivateBoardAgentTasksSurface,
    postBridgeMessage: mocks.postMessage,
  };
});

describe('AgentTasksHostPlaceholder', () => {
  it('activates the Board Agent Tasks surface on mount and deactivates on unmount', () => {
    const { unmount } = render(<AgentTasksHostPlaceholder />);
    expect(mocks.activateBoardAgentTasksSurface).toHaveBeenCalledTimes(1);
    expect(mocks.deactivateBoardAgentTasksSurface).not.toHaveBeenCalled();

    unmount();
    expect(mocks.deactivateBoardAgentTasksSurface).toHaveBeenCalledTimes(1);
  });

  it('renders the embedded spacer when availability is embedded', () => {
    render(<AgentTasksHostPlaceholder />);
    expect(document.querySelector('.agent-tasks-embedded-spacer')).toBeTruthy();
  });

  it('shows the separate-window message when the standalone widget is authoritative', () => {
    render(<AgentTasksHostPlaceholder />);

    act(() => {
      enqueueBoardAgentTasksAvailabilityChanged({ availability: 'separate_window' });
    });

    expect(screen.getByText('Agents is open in a separate window.')).toBeTruthy();
  });

  it('returns to the embedded spacer when availability changes back to embedded', () => {
    render(<AgentTasksHostPlaceholder />);

    act(() => {
      enqueueBoardAgentTasksAvailabilityChanged({ availability: 'separate_window' });
    });
    act(() => {
      enqueueBoardAgentTasksAvailabilityChanged({ availability: 'embedded' });
    });

    expect(document.querySelector('.agent-tasks-embedded-spacer')).toBeTruthy();
  });
});
