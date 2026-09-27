// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { AgentTaskRow } from './AgentTaskRow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function renderRow(onDetach?: () => void): string {
  return renderToStaticMarkup(
    <AgentTaskRow
      id="task-1"
      title="Review the launch behavior"
      status="completed"
      fileCount={0}
      followUpCount={0}
      hasUnreadResult={false}
      isSelected={false}
      onSelect={vi.fn()}
      onDetach={onDetach}
    />
  );
}

describe('AgentTaskRow detached-window action', () => {
  it('renders the selectable row as an accessible button', () => {
    const markup = renderRow();
    expect(markup).toContain('role="button"');
    expect(markup).toContain('tabindex="0"');
    expect(markup).toContain('aria-label="Review the launch behavior"');
    expect(markup).toContain('aria-pressed="false"');
  });

  it('does not render the hover-only action in static markup', () => {
    expect(renderRow(vi.fn())).not.toContain('agent-detach-btn');
  });

  it('omits the action when no detach callback is available', () => {
    expect(renderRow()).not.toContain('agent-detach-btn');
  });

  it('passes its id to selection and detachment callbacks', () => {
    const onSelect = vi.fn();
    const onDetach = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AgentTaskRow
            id="task-1"
            title="Review the launch behavior"
            status="completed"
            fileCount={0}
            followUpCount={0}
            hasUnreadResult={false}
            isSelected={false}
            onSelect={onSelect}
            onDetach={onDetach}
          />,
        );
      });
      const interactiveRow = container.querySelector<HTMLElement>('.sidebar-row > div');
      act(() => {
        interactiveRow?.click();
        interactiveRow?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
      });

      expect(onSelect).toHaveBeenCalledWith('task-1');
      expect(onDetach).toHaveBeenCalledWith('task-1');
    } finally {
      act(() => root.unmount());
    }
  });
});

describe('AgentTaskRow origin badge', () => {
  it('renders the conversation-origin tooltip when originSourceLabel is set', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Review the launch behavior"
        status="completed"
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
        originSourceLabel="From Conversation"
      />
    );
    expect(markup).toContain('From Conversation');
  });

  it('omits the badge when originSourceLabel is undefined', () => {
    expect(renderRow()).not.toContain('From Conversation');
  });
});

describe('AgentTaskRow inline delete confirmation', () => {
  it('renders the inline confirmation instead of the normal row content when isPendingDelete is true', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Review the launch behavior"
        status="completed"
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
        isPendingDelete
        onConfirmDelete={vi.fn()}
        onCancelDeleteRequest={vi.fn()}
      />
    );
    expect(markup).toContain('sidebar-row--confirm-delete');
    expect(markup).toContain('Delete this AgentTask?');
    expect(markup).not.toContain('Review the launch behavior');
    expect(markup).not.toContain('overlay-backdrop');
  });

  it('calls onConfirmDelete with the row id when Delete is clicked', () => {
    const onConfirmDelete = vi.fn();
    const onCancelDeleteRequest = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AgentTaskRow
            id="task-1"
            title="Review the launch behavior"
            status="completed"
            fileCount={0}
            followUpCount={0}
            hasUnreadResult={false}
            isSelected={false}
            onSelect={vi.fn()}
            isPendingDelete
            onConfirmDelete={onConfirmDelete}
            onCancelDeleteRequest={onCancelDeleteRequest}
          />,
        );
      });

      const buttons = container.querySelectorAll<HTMLButtonElement>('.sidebar-row-confirm__btn');
      expect(buttons.length).toBe(2);
      act(() => { buttons[1].click(); });
      expect(onConfirmDelete).toHaveBeenCalledWith('task-1');
      expect(onCancelDeleteRequest).not.toHaveBeenCalled();
    } finally {
      act(() => root.unmount());
    }
  });

  it('calls onCancelDeleteRequest with the row id when Cancel is clicked', () => {
    const onConfirmDelete = vi.fn();
    const onCancelDeleteRequest = vi.fn();
    const container = document.createElement('div');
    const root = createRoot(container);

    try {
      act(() => {
        root.render(
          <AgentTaskRow
            id="task-1"
            title="Review the launch behavior"
            status="completed"
            fileCount={0}
            followUpCount={0}
            hasUnreadResult={false}
            isSelected={false}
            onSelect={vi.fn()}
            isPendingDelete
            onConfirmDelete={onConfirmDelete}
            onCancelDeleteRequest={onCancelDeleteRequest}
          />,
        );
      });

      const buttons = container.querySelectorAll<HTMLButtonElement>('.sidebar-row-confirm__btn');
      act(() => { buttons[0].click(); });
      expect(onCancelDeleteRequest).toHaveBeenCalledWith('task-1');
      expect(onConfirmDelete).not.toHaveBeenCalled();
    } finally {
      act(() => root.unmount());
    }
  });
});
