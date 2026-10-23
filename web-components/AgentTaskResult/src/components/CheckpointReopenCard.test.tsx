// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import type { CheckpointData } from '../types';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mocks = vi.hoisted(() => ({ showCheckpoint: vi.fn() }));

vi.mock('../store/agentStore', () => ({
  agentStore: { showCheckpoint: mocks.showCheckpoint },
}));
vi.mock('../services/api', () => ({}));

import CheckpointReopenCard from './CheckpointReopenCard';

const checkpoint: CheckpointData = {
  checkpoint_id: 'checkpoint-1',
  prompt: '**Which account** should I use?\nSecond line.',
  input_type: 'data',
};

describe('CheckpointReopenCard', () => {
  it('summarizes the skipped question and reopens it on Answer now', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    try {
      act(() => {
        root.render(<CheckpointReopenCard agentTaskId="task-1" checkpoint={checkpoint} />);
      });
      expect(container.querySelector('.agent-task-input-dock-eyebrow')?.textContent).toBe('Input required');
      expect(container.querySelector('.agent-task-input-dock-summary')?.textContent).toBe('Which account should I use?');

      const button = Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent === 'Answer now');
      act(() => {
        button?.click();
      });
      expect(mocks.showCheckpoint).toHaveBeenCalledWith('task-1', checkpoint);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });
});
