// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ResultContent from './ResultContent';
import { applyHostChainExpansion } from '../../app/display/chainExpansionPreference';
import { resetPendingFollowUpsForTests } from '../../store/pendingFollowUps';
import { AgentStore } from '../../store/agentStore/websocketHandlers';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/bridge', () => ({
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
}));

vi.mock('../../services/api', () => ({
  saveAgentTaskAsSkill: vi.fn(),
  submitAgentTaskFeedback: vi.fn(),
  isApiReady: vi.fn().mockReturnValue(false),
  getPendingFollowUps: vi.fn().mockResolvedValue({ follow_ups: [] }),
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: '', api_models_enabled: false }),
}));

function expandedRunIds(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll<HTMLElement>('.history-card--expanded'))
    .map(card => card.dataset.runContent ?? '');
}

describe('a turn snapshotted into history while the chain stays on screen', () => {
  beforeEach(() => {
    resetPendingFollowUpsForTests();
    applyHostChainExpansion('single');
  });

  afterEach(() => {
    applyHostChainExpansion(undefined);
  });

  it('can be opened right away, without reloading the chain', () => {
    const store = new AgentStore();
    store.registerAgent('root-1', 'First question');
    store.setResult('root-1', 'First answer', []);
    store.updateStatus('root-1', 'completed');
    store.beginFollowUpTurn('turn-2', 'root-1');
    store.updateAgentTaskText('root-1', 'Second question');
    store.setResult('root-1', 'Second answer', []);
    store.updateStatus('root-1', 'completed');

    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    // The store hands the same object to the view on every change, so the view re-renders with a reference it already holds.
    const agent = store.getAgent('root-1')!;
    const render = () => act(() => {
      root.render(<ResultContent agentTask={agent} onRetry={() => {}} onContinue={() => {}} />);
    });
    try {
      render();
      expect(container.querySelectorAll('.history-card')).toHaveLength(1);

      store.beginFollowUpTurn('turn-3', 'root-1');
      render();
      expect(container.querySelectorAll('.history-card')).toHaveLength(2);

      act(() => { container.querySelector<HTMLElement>('[data-run-content="turn-2"]')!.click(); });

      expect(expandedRunIds(container)).toEqual(['turn-2']);
    } finally {
      act(() => { root.unmount(); });
      container.remove();
    }
  });

  it('gets a new history list each time a turn is added, so views keyed on the list see the change', () => {
    const store = new AgentStore();
    store.registerAgent('root-1', 'First question');
    store.setResult('root-1', 'First answer', []);
    const before = store.getAgent('root-1')!.agentTaskHistory;

    store.beginFollowUpTurn('turn-2', 'root-1');

    const after = store.getAgent('root-1')!.agentTaskHistory;
    expect(after).not.toBe(before);
    expect(before).toHaveLength(0);
    expect(after.map(turn => turn.id)).toEqual(['root-1']);
  });
});
