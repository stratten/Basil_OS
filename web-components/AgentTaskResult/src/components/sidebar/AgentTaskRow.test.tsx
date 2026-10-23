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

describe('AgentTaskRow paused status', () => {
  it('shows Paused instead of the last running step', () => {
    const markup = renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Count to thirty"
        status="paused"
        currentStep="Running project command"
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
      />
    );
    expect(markup).toContain('aria-label="Count to thirty. Paused"');
    expect(markup).toContain('>Paused</div>');
    expect(markup).not.toContain('Running project command');
  });
});

describe('AgentTaskRow active-status indicator', () => {
  function markupFor(status: string): string {
    return renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Count to thirty"
        status={status}
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
      />
    );
  }

  it.each(['processing', 'routing', 'capturing'])('shows the pulsing dots while %s', (status) => {
    expect(markupFor(status)).toContain('class="pulsing-dots"');
  });

  it('shows the paused and awaiting-input glyphs instead of the dots', () => {
    expect(markupFor('paused')).toContain('aria-label="Paused"');
    expect(markupFor('paused')).not.toContain('pulsing-dots');
    expect(markupFor('awaitingInput')).not.toContain('pulsing-dots');
    expect(markupFor('awaitingInput')).toContain('fill="var(--warning-base)"');
  });

  it('uses the result icon, not the dots, for finished tasks', () => {
    expect(markupFor('completed')).not.toContain('pulsing-dots');
  });
});

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
    expect(markup).toContain('Delete this task?');
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

      const buttons = container.querySelectorAll<HTMLButtonElement>('.inline-delete-confirm__btn');
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

      const buttons = container.querySelectorAll<HTMLButtonElement>('.inline-delete-confirm__btn');
      act(() => { buttons[0].click(); });
      expect(onCancelDeleteRequest).toHaveBeenCalledWith('task-1');
      expect(onConfirmDelete).not.toHaveBeenCalled();
    } finally {
      act(() => root.unmount());
    }
  });
});

describe('AgentTaskRow scheduled follow-up state', () => {
  const dueSoon = new Date(Date.now() + 60 * 60 * 1000).toISOString();

  function markupFor(overrides: { status?: string; nextFollowUpAt?: string; preview?: string; needsApproval?: boolean }): string {
    return renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Watch the deploy"
        status={overrides.status ?? 'completed'}
        preview={overrides.preview}
        nextFollowUpAt={overrides.nextFollowUpAt}
        needsApproval={overrides.needsApproval}
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
      />
    );
  }

  it('shows the shared circular arrow and the check time instead of the result preview', () => {
    const markup = markupFor({ nextFollowUpAt: dueSoon, preview: 'Waiting on work that is still running 2026-10-12T14:01:36+00:00' });
    expect(markup).toContain('agent-task-row__waiting-icon');
    expect(markup).toContain('aria-label="Waiting to check again"');
    expect(markup).toContain('agent-task-row__preview--waiting');
    expect(markup).toContain('Checks again');
    expect(markup).not.toContain('2026-10-12T14:01:36');
    expect(markup).toContain('mask-image');
  });

  it('says the check is imminent once the due time has passed', () => {
    const markup = markupFor({ nextFollowUpAt: new Date(Date.now() - 1000).toISOString() });
    expect(markup).toContain('Checking again soon');
  });

  it('keeps the normal row when no follow-up is scheduled', () => {
    const markup = markupFor({ preview: 'All done' });
    expect(markup).not.toContain('agent-task-row__waiting-icon');
    expect(markup).toContain('All done');
  });

  it('lets an actively running turn use its running indicator instead of the waiting state', () => {
    const markup = markupFor({ status: 'processing', nextFollowUpAt: dueSoon });
    expect(markup).not.toContain('agent-task-row__waiting-icon');
    expect(markup).not.toContain('Checks again');
  });

  it('keeps the approval signal ahead of the waiting icon', () => {
    const markup = markupFor({ nextFollowUpAt: dueSoon, needsApproval: true });
    expect(markup).toContain('approval-attention');
    expect(markup).not.toContain('agent-task-row__waiting-icon');
  });
});

describe('AgentTaskRow archive action', () => {
  function swipeOpenRow(props: { onArchive?: (id: string) => void; archiveLabel?: 'Archive' | 'Unarchive'; status?: string }) {
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => {
      root.render(
        <AgentTaskRow
          id="task-1"
          title="Review the launch behavior"
          status={props.status ?? 'completed'}
          fileCount={0}
          followUpCount={0}
          hasUnreadResult={false}
          isSelected={false}
          onSelect={vi.fn()}
          onRequestDelete={vi.fn()}
          onArchive={props.onArchive}
          archiveLabel={props.archiveLabel}
        />,
      );
    });
    const row = container.querySelector<HTMLElement>('.sidebar-row > div');
    act(() => {
      row?.dispatchEvent(new WheelEvent('wheel', { deltaX: 130, deltaY: 0, bubbles: true }));
    });
    return { container, unmount: () => act(() => root.unmount()) };
  }

  it('reveals Archive beside Delete after a swipe and archives by row id', () => {
    const onArchive = vi.fn();
    const { container, unmount } = swipeOpenRow({ onArchive });
    const button = container.querySelector<HTMLButtonElement>('.swipe-archive-btn');
    expect(button?.textContent).toContain('Archive');
    act(() => button?.click());
    expect(onArchive).toHaveBeenCalledWith('task-1');
    unmount();
  });

  it('labels the action Unarchive in the Archived view', () => {
    const { container, unmount } = swipeOpenRow({ onArchive: vi.fn(), archiveLabel: 'Unarchive' });
    expect(container.querySelector('.swipe-archive-btn')?.textContent).toContain('Unarchive');
    unmount();
  });

  it('renders no archive action when no callback is supplied', () => {
    const { container, unmount } = swipeOpenRow({});
    expect(container.querySelector('.swipe-archive-btn')).toBeNull();
    unmount();
  });
});

describe('AgentTaskRow schedule state', () => {
  function scheduleMarkup(props: { scheduleActive?: boolean; status?: string; isPendingDelete?: boolean; deleteConfirmLabel?: string }): string {
    return renderToStaticMarkup(
      <AgentTaskRow
        id="schedule-1"
        title="Weekly summary"
        status={props.status ?? 'completed'}
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
        onRequestDelete={vi.fn()}
        scheduleActive={props.scheduleActive}
        isPendingDelete={props.isPendingDelete}
        deleteConfirmLabel={props.deleteConfirmLabel}
        onConfirmDelete={vi.fn()}
        onCancelDeleteRequest={vi.fn()}
      />
    );
  }

  it('shows a solid dot for an active schedule and a hollow ring for an inactive one', () => {
    const active = scheduleMarkup({ scheduleActive: true });
    expect(active).toContain('agent-task-row__schedule-dot is-active');
    expect(active).toContain('aria-label="Schedule active"');
    const inactive = scheduleMarkup({ scheduleActive: false });
    expect(inactive).toContain('agent-task-row__schedule-dot is-inactive');
    expect(inactive).toContain('aria-label="Schedule inactive"');
  });

  it('keeps the failure mark beside the dot and omits the dot on ordinary rows', () => {
    const failed = scheduleMarkup({ scheduleActive: true, status: 'failed' });
    expect(failed).toContain('is-active');
    expect(failed).toContain('var(--error-base)');
    expect(scheduleMarkup({})).not.toContain('agent-task-row__schedule-dot');
  });

  it('asks for confirmation with the schedule wording before deleting', () => {
    const markup = scheduleMarkup({ scheduleActive: true, isPendingDelete: true, deleteConfirmLabel: 'Delete this schedule?' });
    expect(markup).toContain('Delete this schedule?');
    expect(markup).not.toContain('agent-task-row__schedule-dot');
  });
});
