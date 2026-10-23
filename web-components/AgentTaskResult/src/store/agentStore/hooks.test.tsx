// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it } from 'vitest';
import { agentStore } from './singleton';
import { useAgent, useSelectedAgent } from './hooks';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let root: Root | undefined;
let container: HTMLDivElement | undefined;
const createdAgentIds: string[] = [];

function registerAgent(id: string) {
  createdAgentIds.push(id);
  agentStore.registerAgent(id);
}

function render(ui: JSX.Element) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(ui);
  });
}

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
  for (const id of createdAgentIds.splice(0)) agentStore.removeAgent(id);
  agentStore.deselectAgent();
});

describe('agent store hooks', () => {
  it('re-renders the selected-agent consumer only for its own task updates', () => {
    const selectedId = 'selected-agent';
    const unrelatedId = 'unrelated-agent';
    let renders = 0;

    function SelectedAgentView() {
      renders++;
      const agent = useSelectedAgent();
      return <output>{agent?.agentTaskId}:{agent?.originalPrompt}</output>;
    }

    act(() => {
      registerAgent(selectedId);
      registerAgent(unrelatedId);
      agentStore.selectAgent(selectedId);
    });
    render(<SelectedAgentView />);
    const afterInitialRender = renders;

    act(() => {
      agentStore.updateAgentTaskText(unrelatedId, 'unrelated update');
    });
    expect(renders).toBe(afterInitialRender);

    act(() => {
      agentStore.updateAgentTaskText(selectedId, 'selected update');
    });
    expect(renders).toBe(afterInitialRender + 1);
    expect(container?.textContent).toBe('selected-agent:selected update');
  });

  it('re-renders when the selected agent changes', () => {
    const firstId = 'first-selected-agent';
    const secondId = 'second-selected-agent';

    function SelectedAgentView() {
      const agent = useSelectedAgent();
      return <output>{agent?.agentTaskId}</output>;
    }

    act(() => {
      registerAgent(firstId);
      registerAgent(secondId);
      agentStore.selectAgent(firstId);
    });
    render(<SelectedAgentView />);
    expect(container?.textContent).toBe(firstId);

    act(() => {
      agentStore.selectAgent(secondId);
    });
    expect(container?.textContent).toBe(secondId);
  });

  it('re-renders a per-agent consumer only for that agent', () => {
    const observedId = 'observed-agent';
    const unrelatedId = 'other-agent';
    let renders = 0;

    function AgentView() {
      renders++;
      const agent = useAgent(observedId);
      return <output>{agent?.originalPrompt}</output>;
    }

    act(() => {
      registerAgent(observedId);
      registerAgent(unrelatedId);
    });
    render(<AgentView />);
    const afterInitialRender = renders;

    act(() => {
      agentStore.updateAgentTaskText(unrelatedId, 'other update');
    });
    expect(renders).toBe(afterInitialRender);

    act(() => {
      agentStore.updateAgentTaskText(observedId, 'observed update');
    });
    expect(renders).toBe(afterInitialRender + 1);
    expect(container?.textContent).toBe('observed update');
  });
});
