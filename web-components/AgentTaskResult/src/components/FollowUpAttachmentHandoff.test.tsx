// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RunControlComposer from './RunControlComposer';
import TextFollowUp from './TextFollowUp';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../services/api', () => ({
  getReasoningModels: vi.fn().mockResolvedValue({ models: [], current_model: '' }),
  processAgentTask: vi.fn().mockResolvedValue(undefined),
  pauseSession: vi.fn(),
  resumeSession: vi.fn(),
  sendRunMessage: vi.fn(),
}));

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function Surfaces({ followUp, runControl }: { followUp: boolean; runControl: boolean }) {
  return (
    <>
      {runControl && <RunControlComposer turnTaskId="turn-1" mode="running" deliveredNoteIds={new Set()} />}
      {followUp && <TextFollowUp agentTaskId="task-1" onCancel={vi.fn()} alwaysVisible />}
    </>
  );
}

describe('follow-up attachment handoff', () => {
  it('keeps the follow-up box receiving files after the run-control box it replaced unmounts', async () => {
    await act(async () => {
      root.render(<Surfaces followUp={false} runControl />);
    });
    // The task finishes: the follow-up box mounts while the run-control box is still fading out.
    await act(async () => {
      root.render(<Surfaces followUp runControl />);
    });
    // The fade ends and the run-control box unmounts.
    await act(async () => {
      root.render(<Surfaces followUp runControl={false} />);
    });

    await act(async () => {
      window.basilAgentTask?.onFilesPicked(['/tmp/report.png']);
    });

    expect(container.querySelector('.text-followup-references')?.textContent).toContain('report.png');

    const remove = container.querySelector<HTMLButtonElement>('[aria-label="Remove report.png"]');
    expect(remove).not.toBeNull();
    await act(async () => remove?.click());
    expect(container.querySelector('.text-followup-references')).toBeNull();
  });
});
