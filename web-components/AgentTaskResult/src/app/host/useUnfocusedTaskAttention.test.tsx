// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { agentStore } from '../../store/agentStore';
import { taskNeedsCollapsedAttention, taskNeedsInput, useUnfocusedTaskAttention } from './useUnfocusedTaskAttention';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const noneDetached: ReadonlySet<string> = new Set();

function Harness({
  enabled,
  detached = noneDetached,
  onNeedsInput,
  onTurnCompleted,
}: {
  enabled: boolean;
  detached?: ReadonlySet<string>;
  onNeedsInput: () => void;
  onTurnCompleted: () => void;
}) {
  useUnfocusedTaskAttention({ enabled, detachedRootsElsewhere: detached, onNeedsInput, onTurnCompleted });
  return null;
}

describe('task attention rules', () => {
  const base = { agentTaskId: 'a', rootTaskId: 'a', status: 'completed', isCanceled: false, showApprovalPrompt: false, showTokenConnectPrompt: false, showCheckpointPrompt: false } as const;

  it('counts an in-flight task and a task waiting on the user, and nothing else', () => {
    expect(taskNeedsCollapsedAttention({ ...base, status: 'processing' }, noneDetached)).toBe(true);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'routing' }, noneDetached)).toBe(true);
    expect(taskNeedsCollapsedAttention({ ...base, showApprovalPrompt: true }, noneDetached)).toBe(true);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'awaitingInput' }, noneDetached)).toBe(true);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'completed' }, noneDetached)).toBe(false);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'failed' }, noneDetached)).toBe(false);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'paused' }, noneDetached)).toBe(false);
  });

  it('ignores a canceled task and a task another window owns', () => {
    expect(taskNeedsCollapsedAttention({ ...base, status: 'processing', isCanceled: true }, noneDetached)).toBe(false);
    expect(taskNeedsCollapsedAttention({ ...base, status: 'processing' }, new Set(['a']))).toBe(false);
    expect(taskNeedsCollapsedAttention({ ...base, agentTaskId: 'child', rootTaskId: 'a', status: 'processing' }, new Set(['a']))).toBe(false);
  });

  it('reads approval, token, checkpoint and awaiting-input as needing the user', () => {
    expect(taskNeedsInput({ ...base, showTokenConnectPrompt: true })).toBe(true);
    expect(taskNeedsInput({ ...base, showCheckpointPrompt: true })).toBe(true);
    expect(taskNeedsInput({ ...base, status: 'awaitingInput' })).toBe(true);
    expect(taskNeedsInput(base)).toBe(false);
  });
});

describe('useUnfocusedTaskAttention', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;
  const onNeedsInput = vi.fn();
  const onTurnCompleted = vi.fn();

  function mount(props: Partial<Parameters<typeof Harness>[0]> = {}) {
    container = document.createElement('div');
    root = createRoot(container);
    act(() => root.render(
      <Harness enabled onNeedsInput={onNeedsInput} onTurnCompleted={onTurnCompleted} {...props} />,
    ));
  }

  function addTask(id: string, status: 'processing' | 'completed' = 'processing') {
    act(() => {
      agentStore.registerAgent(id, 'request', { select: false });
      agentStore.updateStatus(id, status);
    });
  }

  beforeEach(() => {
    onNeedsInput.mockReset();
    onTurnCompleted.mockReset();
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
    act(() => {
      agentStore.registerAgent('focused', 'focused request');
      agentStore.selectAgent('focused');
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    for (const agent of agentStore.getAllAgents()) agentStore.removeAgent(agent.agentTaskId);
  });

  it('reports an unfocused task that finishes a turn while collapsed', () => {
    mount();
    addTask('other');
    expect(onTurnCompleted).not.toHaveBeenCalled();

    act(() => agentStore.updateStatus('other', 'completed'));

    expect(onTurnCompleted).toHaveBeenCalledTimes(1);
    expect(onNeedsInput).not.toHaveBeenCalled();
  });

  it('reports an unfocused task that starts waiting on the user', () => {
    mount();
    addTask('other');

    act(() => agentStore.updateStatus('other', 'awaitingInput'));

    expect(onNeedsInput).toHaveBeenCalledTimes(1);
    expect(onTurnCompleted).not.toHaveBeenCalled();
  });

  it('leaves the focused task to its own paths', () => {
    mount();
    act(() => agentStore.updateStatus('focused', 'processing'));
    act(() => agentStore.updateStatus('focused', 'awaitingInput'));
    act(() => agentStore.updateStatus('focused', 'completed'));

    expect(onNeedsInput).not.toHaveBeenCalled();
    expect(onTurnCompleted).not.toHaveBeenCalled();
  });

  it('reports nothing while the widget is expanded and does not replay it on collapse', () => {
    mount({ enabled: false });
    addTask('other');
    act(() => agentStore.updateStatus('other', 'completed'));
    expect(onTurnCompleted).not.toHaveBeenCalled();

    act(() => root.render(<Harness enabled onNeedsInput={onNeedsInput} onTurnCompleted={onTurnCompleted} />));

    expect(onTurnCompleted).not.toHaveBeenCalled();
    expect(onNeedsInput).not.toHaveBeenCalled();
  });

  it('does not report a task that was already waiting before the hook started watching', () => {
    addTask('earlier');
    act(() => agentStore.updateStatus('earlier', 'awaitingInput'));

    mount();
    act(() => agentStore.updateStatus('earlier', 'awaitingInput'));

    expect(onNeedsInput).not.toHaveBeenCalled();
  });

  it('ignores a task another window owns', () => {
    mount({ detached: new Set(['other']) });
    addTask('other');
    act(() => agentStore.updateStatus('other', 'completed'));

    expect(onTurnCompleted).not.toHaveBeenCalled();
  });

  it('does not report a canceled task as a completion', () => {
    mount();
    addTask('other');

    act(() => {
      agentStore.markCanceled('other');
      agentStore.updateStatus('other', 'completed');
    });

    expect(onTurnCompleted).not.toHaveBeenCalled();
  });
});
