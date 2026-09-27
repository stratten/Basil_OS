// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AgentTaskOriginChip from './AgentTaskOriginChip';

const mocks = vi.hoisted(() => ({
  getTodoOriginDetail: vi.fn(),
  openAgentTaskOrigin: vi.fn(),
}));

vi.mock('../../services/bridge', () => ({
  openAgentTaskOrigin: mocks.openAgentTaskOrigin,
}));

vi.mock('../../services/api', () => ({
  getTodoOriginDetail: mocks.getTodoOriginDetail,
}));

describe('AgentTaskOriginChip', () => {
  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    mocks.getTodoOriginDetail.mockReset();
    mocks.openAgentTaskOrigin.mockReset();
  });

  it('renders an actionable To-Do source chip', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskOriginChip originType="todo" originId="todo-123" />,
    );

    expect(markup).toContain('From To-Do');
    expect(markup).toContain('Open to-do');
  });

  it('renders an unknown source as a disabled chip', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskOriginChip originType="unrecognized_source" originId="source-123" />,
    );

    expect(markup).toContain('From unrecognized source');
    expect(markup).toContain('aria-disabled="true"');
  });

  it('adds an actionable meeting lineage chip for a meeting-sourced To-Do', async () => {
    mocks.getTodoOriginDetail.mockResolvedValue({
      id: 'todo-meeting',
      sources: [{
        source_kind: 'meeting_analysis_proposal',
        source_id: 'meeting-123:analysis.json:proposal-1',
        source_locator: { meeting_id: 'meeting-123', filename: 'analysis.json', proposal_id: 'proposal-1' },
      }],
    });
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(<AgentTaskOriginChip originType="todo" originId="todo-meeting" />);
      });
      await vi.waitFor(() => {
        expect(container.textContent).toContain('Originally from Meeting');
      });

      const buttons = container.querySelectorAll('button');
      expect(buttons).toHaveLength(2);
      act(() => {
        (buttons[1] as HTMLButtonElement).click();
      });
      expect(mocks.openAgentTaskOrigin).toHaveBeenCalledWith('meeting', 'meeting-123');
    } finally {
      act(() => root.unmount());
    }
  });

  it('keeps an ordinary To-Do to a single provenance chip', async () => {
    mocks.getTodoOriginDetail.mockResolvedValue({
      id: 'todo-ordinary',
      sources: [{
        source_kind: 'manual',
        source_id: 'user',
        source_locator: {},
      }],
    });
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(<AgentTaskOriginChip originType="todo" originId="todo-ordinary" />);
      });
      await vi.waitFor(() => expect(mocks.getTodoOriginDetail).toHaveBeenCalled());
      expect(container.textContent).toBe('From To-Do');
    } finally {
      act(() => root.unmount());
    }
  });

  it('does not block the primary chip while meeting lineage is loading', async () => {
    mocks.getTodoOriginDetail.mockReturnValue(new Promise(() => undefined));
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(<AgentTaskOriginChip originType="todo" originId="todo-loading" />);
      });
      expect(container.textContent).toBe('From To-Do');
      expect(container.textContent).not.toContain('Originally from Meeting');
    } finally {
      act(() => root.unmount());
    }
  });

  it('retains the To-Do chip when lineage lookup fails', async () => {
    mocks.getTodoOriginDetail.mockRejectedValue(new Error('offline'));
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      await act(async () => {
        root.render(<AgentTaskOriginChip originType="todo" originId="todo-failed" />);
      });
      await vi.waitFor(() => expect(mocks.getTodoOriginDetail).toHaveBeenCalled());
      expect(container.textContent).toBe('From To-Do');
    } finally {
      act(() => root.unmount());
    }
  });
});
