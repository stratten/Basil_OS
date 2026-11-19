// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  hydrateAgentFromBackend: vi.fn(),
  getAgent: vi.fn(),
}));

vi.mock('../../app/agents/agentHydration', () => ({
  hydrateAgentFromBackend: mocks.hydrateAgentFromBackend,
}));

vi.mock('../../store/agentStore', () => ({
  agentStore: { getAgent: mocks.getAgent },
}));

let CheckpointRecoveryCard: typeof import('./CheckpointRecoveryCard').default;
let container: HTMLDivElement;
let root: Root;

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeAll(async () => {
  CheckpointRecoveryCard = (await import('./CheckpointRecoveryCard')).default;
});

beforeEach(() => {
  Object.values(mocks).forEach(mock => mock.mockReset());
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function render(prompt: string | null = 'Where is Speakeasy located?', questionKey = 'cp-1') {
  await act(async () => {
    root.render(<CheckpointRecoveryCard agentTaskId="task-1" prompt={prompt ?? undefined} questionKey={questionKey} />);
  });
}

function button(): HTMLButtonElement {
  const element = container.querySelector<HTMLButtonElement>('button');
  if (!element) throw new Error('Button missing');
  return element;
}

describe('CheckpointRecoveryCard', () => {
  it('loads the question as soon as it appears and shows a disabled loading button meanwhile', async () => {
    let finish: (outcome: string) => void = () => undefined;
    mocks.hydrateAgentFromBackend.mockReturnValue(new Promise<string>(resolve => { finish = resolve; }));
    mocks.getAgent.mockReturnValue({ status: 'awaitingInput' });

    await render();

    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledWith('task-1');
    expect(button().disabled).toBe(true);
    expect(button().textContent).toBe('Loading…');
    expect(container.textContent).toContain('Input required');
    expect(container.textContent).toContain('Where is Speakeasy located?');

    await act(async () => finish('hydrated'));
    expect(button().disabled).toBe(false);
    expect(button().textContent).toBe('Answer now');
  });

  it('keeps offering "Answer now" when the backend is still waiting but nothing came back, and asks again on click', async () => {
    mocks.hydrateAgentFromBackend.mockResolvedValue('hydrated');
    mocks.getAgent.mockReturnValue({ status: 'awaitingInput' });
    await render();
    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledTimes(1);

    await act(async () => button().click());

    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledTimes(2);
  });

  it('keeps the button when the read failed, so the user can try again', async () => {
    mocks.hydrateAgentFromBackend.mockRejectedValue(new Error('offline'));
    mocks.getAgent.mockReturnValue({ status: 'processing' });
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    await render();

    expect(button().textContent).toBe('Answer now');
    warn.mockRestore();
  });

  it('goes away when the backend confirms the run is no longer waiting', async () => {
    mocks.hydrateAgentFromBackend.mockResolvedValue('hydrated');
    mocks.getAgent.mockReturnValue({ status: 'processing' });

    await render();

    expect(container.querySelector('section')).toBeNull();
  });

  it('leaves the rest to the answer card once the question is in the store', async () => {
    mocks.hydrateAgentFromBackend.mockResolvedValue('hydrated');
    mocks.getAgent.mockReturnValue({ status: 'awaitingInput', currentCheckpoint: { checkpoint_id: 'cp-1' } });

    await render();

    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledTimes(1);
    expect(button().disabled).toBe(true);
  });

  it('says what it is doing when it has no question text yet', async () => {
    mocks.hydrateAgentFromBackend.mockReturnValue(new Promise(() => undefined));

    await render(null, 'status');

    expect(container.textContent).toContain('Loading the question Basil asked');
  });

  it('loads again for a different question', async () => {
    mocks.hydrateAgentFromBackend.mockResolvedValue('hydrated');
    mocks.getAgent.mockReturnValue({ status: 'awaitingInput' });
    await render('First?', 'cp-1');

    await render('Second?', 'cp-2');

    expect(mocks.hydrateAgentFromBackend).toHaveBeenCalledTimes(2);
  });
});
