// @vitest-environment jsdom
import { act, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { hydrateAgentFromBackend } from './agentHydration';
import { useAgentSelection } from './useAgentSelection';
import { agentStore } from '../store/agentStore';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('./agentHydration', () => ({
  hydrateAgentFromBackend: vi.fn(),
}));

const noOp = () => undefined;

function SelectionHarness({ onReady }: { onReady: (selectTask: (agentTaskId: string) => void) => void }) {
  const { handleViewAgentTask } = useAgentSelection({
    setViewedDetail: noOp,
    setSelectedScheduledAgentTaskId: noOp,
    setCreateScheduledMode: noOp,
    setScheduledListVersion: noOp,
    setPendingAgentTaskSelection: noOp,
    selectedAgent: null,
    viewedDetail: null,
  });

  useEffect(() => {
    onReady(handleViewAgentTask);
  }, [handleViewAgentTask, onReady]);

  return null;
}

describe('useAgentSelection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('rehydrates an already-known live task when it is selected', () => {
    const agentTaskId = 'already-known-provider-task';
    agentStore.registerAgent(agentTaskId);
    agentStore.updateStatus(agentTaskId, 'processing');
    const container = document.createElement('div');
    const root = createRoot(container);
    let selectTask: ((taskId: string) => void) | undefined;

    try {
      act(() => {
        root.render(<SelectionHarness onReady={handler => { selectTask = handler; }} />);
      });

      expect(selectTask).toBeDefined();
      act(() => {
        selectTask?.(agentTaskId);
      });

      expect(hydrateAgentFromBackend).toHaveBeenCalledTimes(1);
      expect(hydrateAgentFromBackend).toHaveBeenCalledWith(agentTaskId);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('keeps a new selection pending through a superseded hydration request', async () => {
    const agentTaskId = 'newly-selected-task';
    const pendingSelections = vi.fn();
    (hydrateAgentFromBackend as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce('superseded')
      .mockResolvedValueOnce('hydrated');
    const container = document.createElement('div');
    const root = createRoot(container);
    let selectTask: ((taskId: string) => Promise<void>) | undefined;

    function PendingSelectionHarness() {
      const { handleViewAgentTask } = useAgentSelection({
        setViewedDetail: noOp,
        setSelectedScheduledAgentTaskId: noOp,
        setCreateScheduledMode: noOp,
        setScheduledListVersion: noOp,
        setPendingAgentTaskSelection: pendingSelections,
        selectedAgent: null,
        viewedDetail: null,
      });

      useEffect(() => {
        selectTask = handleViewAgentTask;
      }, [handleViewAgentTask]);

      return null;
    }

    try {
      await act(async () => {
        root.render(<PendingSelectionHarness />);
      });

      await act(async () => {
        await selectTask?.(agentTaskId);
      });

      expect(hydrateAgentFromBackend).toHaveBeenNthCalledWith(1, agentTaskId);
      expect(hydrateAgentFromBackend).toHaveBeenNthCalledWith(2, agentTaskId);
      expect(agentStore.getSelectedAgentId()).toBe(agentTaskId);
      expect(pendingSelections).toHaveBeenCalledWith({ agentTaskId, epoch: 1 });
      expect(pendingSelections).toHaveBeenLastCalledWith(expect.any(Function));
    } finally {
      act(() => {
        root.unmount();
        agentStore.removeAgent(agentTaskId);
      });
      container.remove();
    }
  });
});
