// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DisplayableAgentTask } from '../types';
import { reportAgentStatus } from '../services/bridge';
import { useAgentStatusReporting } from './useAgentStatusReporting';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/bridge', () => ({
  reportAgentStatus: vi.fn(),
}));

const completedTask = {
  agentTaskId: 'task-1',
  status: 'completed',
  result: 'done',
} as unknown as DisplayableAgentTask;

function Harness({ detached }: { detached: boolean }) {
  useAgentStatusReporting({
    focusedAgent: completedTask,
    selectedScheduledAgentTaskId: null,
    createScheduledMode: false,
    focusedAgentDetached: detached,
  });
  return null;
}

describe('useAgentStatusReporting', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  function render(detached: boolean) {
    container = document.createElement('div');
    root = createRoot(container);
    act(() => root.render(<Harness detached={detached} />));
  }

  afterEach(() => {
    act(() => root.unmount());
    vi.clearAllMocks();
  });

  it('reports the focused task when it is shown in this window', () => {
    render(false);
    expect(reportAgentStatus).toHaveBeenLastCalledWith(false, true, true, 'task-1', true);
  });

  it('reports no focused task when the task is open in its own detached window', () => {
    render(true);
    expect(reportAgentStatus).toHaveBeenLastCalledWith(false, false, false, null, false);
  });
});
