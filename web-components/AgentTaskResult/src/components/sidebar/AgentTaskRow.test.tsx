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

  it.each(['processing', 'routing', 'capturing'])('shows the processing rail spinner while %s', (status) => {
    expect(markupFor(status)).toContain('class="agent-task-processing-spinner"');
  });

  it('shows the paused and awaiting-input glyphs instead of the dots', () => {
    expect(markupFor('paused')).toContain('aria-label="Paused"');
    expect(markupFor('paused')).not.toContain('agent-task-processing-spinner');
    expect(markupFor('awaitingInput')).not.toContain('agent-task-processing-spinner');
    expect(markupFor('awaitingInput')).toContain('fill="var(--warning-base)"');
  });

  it('uses the result icon, not the dots, for finished tasks', () => {
    expect(markupFor('completed')).not.toContain('agent-task-processing-spinner');
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

describe('AgentTaskRow aligned icon gutter', () => {
  function container(props: { status?: string; scheduledRunSourceTitle?: string; originSourceLabel?: string; hasUnreadResult?: boolean }): HTMLElement {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Review the launch behavior"
        status={props.status ?? 'completed'}
        preview="All done"
        fileCount={0}
        followUpCount={0}
        hasUnreadResult={props.hasUnreadResult ?? false}
        isSelected={false}
        onSelect={vi.fn()}
        scheduledRunSourceTitle={props.scheduledRunSourceTitle}
        originSourceLabel={props.originSourceLabel}
      />
    );
    return host;
  }

  it('puts the status icon in the gutter slot, outside the title text', () => {
    const host = container({});
    const main = host.querySelector('.agent-task-row__main--aligned');
    expect(main).not.toBeNull();
    expect(main?.querySelector(':scope > .agent-task-row__status-slot svg')).not.toBeNull();
    expect(host.querySelector('.agent-task-row__text .agent-task-row__status-slot')).toBeNull();
  });

  it('puts the schedule icon in the origin slot below the status slot, not inside the title', () => {
    const host = container({ scheduledRunSourceTitle: 'Weekly summary' });
    const slot = host.querySelector('.agent-task-row__main--aligned > .agent-task-row__origin-slot');
    expect(slot?.querySelector('[aria-label="From schedule: Weekly summary"]')).not.toBeNull();
    expect(host.querySelector('.agent-task-row__title .agent-task-row__origin-icon')).toBeNull();
  });

  it('puts the conversation-origin icon in the origin slot', () => {
    const host = container({ originSourceLabel: 'From Conversation' });
    expect(host.querySelector('.agent-task-row__origin-slot [aria-label="From Conversation"]')).not.toBeNull();
  });

  it('renders no origin slot for an ordinary row', () => {
    expect(container({}).querySelector('.agent-task-row__origin-slot')).toBeNull();
  });

  it('renders the unread badge in the trailing container and nothing when there is no trailing state', () => {
    expect(container({ hasUnreadResult: true }).querySelector('.agent-task-row__trailing .unread-badge')).not.toBeNull();
    expect(container({}).querySelector('.agent-task-row__trailing')).toBeNull();
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
    expect(markup).toContain('inline-delete-confirm--stacked');
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

  function markupFor(overrides: { status?: string; nextFollowUpAt?: string; preview?: string; needsApproval?: boolean; attentionPreview?: string }): string {
    return renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Watch the deploy"
        status={overrides.status ?? 'completed'}
        preview={overrides.preview}
        nextFollowUpAt={overrides.nextFollowUpAt}
        needsApproval={overrides.needsApproval}
        attentionPreview={overrides.attentionPreview}
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
    expect(markup).toContain('agent-task-processing-spinner--attention');
    expect(markup).not.toContain('agent-task-row__waiting-icon');
  });

  it('prints the specific wait instead of a generic approval line', () => {
    expect(markupFor({ needsApproval: true, attentionPreview: 'Token needed' })).toContain('Token needed');
    expect(markupFor({ needsApproval: true, attentionPreview: 'Token needed' })).not.toContain('Approval needed');
    expect(markupFor({ needsApproval: true })).toContain('Approval needed');
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

describe('AgentTaskRow checklist badge', () => {
  function markupWith(extra: Partial<React.ComponentProps<typeof AgentTaskRow>>): string {
    return renderToStaticMarkup(
      <AgentTaskRow
        id="task-1"
        title="Sort out the insurance"
        status="completed"
        timestamp="2026-11-03T09:00:00Z"
        fileCount={2}
        followUpCount={0}
        hasUnreadResult={false}
        isSelected={false}
        onSelect={vi.fn()}
        {...extra}
      />
    );
  }

  it('shows done over total after the file count, with a label a screen reader can use', () => {
    const markup = markupWith({ checklistRootId: 'task-1', checklistDone: 2, checklistTotal: 5 });
    expect(markup).toContain('agent-task-row__checklist');
    expect(markup).toContain('aria-label="Checklist, 2 of 5 done"');
    expect(markup).toMatch(/<svg[^>]*>.*<\/svg>2\/5/);
    expect(markup.indexOf('2/5')).toBeGreaterThan(markup.lastIndexOf('agent-task-row__meta-item'));
  });

  it('renders nothing when the chain has no items, or the row is not a task chain', () => {
    expect(markupWith({ checklistRootId: 'task-1', checklistDone: 0, checklistTotal: 0 })).not.toContain('agent-task-row__checklist');
    expect(markupWith({ checklistDone: 2, checklistTotal: 5 })).not.toContain('agent-task-row__checklist');
  });

  it('still shows the badge on a row with no date and no files', () => {
    const markup = markupWith({ timestamp: undefined, fileCount: 0, checklistRootId: 'task-1', checklistDone: 1, checklistTotal: 3 });
    expect(markup).toContain('1/3');
  });
});

describe('AgentTaskRow schedule activate switch and Run now', () => {
  function mountSchedule(props: Partial<React.ComponentProps<typeof AgentTaskRow>>) {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    const onSelect = vi.fn();
    act(() => {
      root.render(
        <AgentTaskRow
          id="schedule-1"
          title="Weekly summary"
          status="completed"
          fileCount={0}
          followUpCount={0}
          hasUnreadResult={false}
          isSelected={false}
          onSelect={onSelect}
          onRequestDelete={vi.fn()}
          scheduleActive
          {...props}
        />,
      );
    });
    const row = container.querySelector<HTMLElement>('.sidebar-row')!;
    const hover = () => act(() => { row.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })); });
    const unmount = () => { act(() => root.unmount()); container.remove(); };
    return { container, onSelect, hover, unmount };
  }

  const switchOf = (container: HTMLElement) => container.querySelector<HTMLButtonElement>('.agent-task-row__schedule-dot-btn');
  const runButtonOf = (container: HTMLElement) => container.querySelector<HTMLButtonElement>('.agent-schedule-run-btn');

  it('makes the status dot a switch that is always visible, with a tooltip saying what a click does', () => {
    const active = mountSchedule({ onToggleSchedule: vi.fn() });
    const activeSwitch = switchOf(active.container)!;
    expect(activeSwitch.getAttribute('role')).toBe('switch');
    expect(activeSwitch.getAttribute('aria-checked')).toBe('true');
    expect(activeSwitch.getAttribute('title')).toBe('Active. Click to deactivate');
    expect(activeSwitch.querySelector('.agent-task-row__schedule-dot.is-active')).not.toBeNull();
    active.unmount();

    const inactive = mountSchedule({ scheduleActive: false, onToggleSchedule: vi.fn() });
    const inactiveSwitch = switchOf(inactive.container)!;
    expect(inactiveSwitch.getAttribute('aria-checked')).toBe('false');
    expect(inactiveSwitch.getAttribute('title')).toBe('Inactive. Click to activate');
    expect(inactiveSwitch.querySelector('.agent-task-row__schedule-dot.is-inactive')).not.toBeNull();
    inactive.unmount();
  });

  it('sends the state to set when the dot is clicked, without selecting or detaching the row', () => {
    const onToggleSchedule = vi.fn();
    const onDetach = vi.fn();
    const { container, onSelect, unmount } = mountSchedule({ onToggleSchedule, onDetach });
    const dot = switchOf(container)!;
    act(() => dot.click());
    act(() => { dot.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })); });
    expect(onToggleSchedule).toHaveBeenCalledWith('schedule-1', false);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onDetach).not.toHaveBeenCalled();
    unmount();

    const inactive = mountSchedule({ scheduleActive: false, onToggleSchedule });
    act(() => switchOf(inactive.container)!.click());
    act(() => switchOf(inactive.container)!.click());
    expect(onToggleSchedule).toHaveBeenNthCalledWith(2, 'schedule-1', true);
    expect(onToggleSchedule).toHaveBeenNthCalledWith(3, 'schedule-1', true);
    inactive.unmount();
  });

  it('keeps Enter and Space on the dot from selecting the row, so the keyboard can operate the switch', () => {
    const { container, onSelect, unmount } = mountSchedule({ onToggleSchedule: vi.fn() });
    const dot = switchOf(container)!;
    for (const key of ['Enter', ' ']) {
      act(() => { dot.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })); });
    }
    expect(onSelect).not.toHaveBeenCalled();
    unmount();
  });

  it('leaves the dot a plain indicator without a handler and on rows that are not schedules', () => {
    const noHandler = mountSchedule({});
    expect(switchOf(noHandler.container)).toBeNull();
    expect(noHandler.container.querySelector('.agent-task-row__schedule-dot[role="img"]')).not.toBeNull();
    noHandler.unmount();

    const notSchedule = mountSchedule({ scheduleActive: undefined, onToggleSchedule: vi.fn(), onRunSchedule: vi.fn() });
    notSchedule.hover();
    expect(switchOf(notSchedule.container)).toBeNull();
    expect(runButtonOf(notSchedule.container)).toBeNull();
    notSchedule.unmount();
  });

  it('shows the Run now button only on hover, for an active and an inactive schedule alike', () => {
    for (const scheduleActive of [true, false]) {
      const { container, hover, unmount } = mountSchedule({ scheduleActive, onRunSchedule: vi.fn() });
      expect(runButtonOf(container)).toBeNull();
      hover();
      const button = runButtonOf(container)!;
      expect(button.getAttribute('aria-label')).toBe('Run this schedule now');
      expect(button.getAttribute('title')).toBe('Run now');
      expect(button.querySelector('circle')).not.toBeNull();
      unmount();
    }
  });

  it('starts one run with the schedule id, without selecting the row, and says it started', async () => {
    const onRunSchedule = vi.fn().mockResolvedValue({ ok: true });
    const { container, onSelect, hover, unmount } = mountSchedule({ onRunSchedule });
    hover();
    await act(async () => { runButtonOf(container)!.click(); });
    expect(onRunSchedule).toHaveBeenCalledTimes(1);
    expect(onRunSchedule).toHaveBeenCalledWith('schedule-1');
    expect(onSelect).not.toHaveBeenCalled();
    const notice = container.querySelector('[role="status"]')!;
    expect(notice.textContent).toBe('Run started');
    expect(notice.className).toContain('agent-task-row__preview--waiting');
    unmount();
  });

  it('shows the reason in the warning color when the run could not start', async () => {
    const onRunSchedule = vi.fn().mockResolvedValue({ ok: false, message: 'Scheduled task not found' });
    const { container, hover, unmount } = mountSchedule({ onRunSchedule });
    hover();
    await act(async () => { runButtonOf(container)!.click(); });
    const notice = container.querySelector('[role="status"]')!;
    expect(notice.textContent).toBe('Scheduled task not found');
    expect(notice.className).toContain('agent-task-row__preview--warning');
    unmount();
  });

  it('cannot start a second run while the first is still starting, even after the pointer leaves', async () => {
    let finish: (outcome: { ok: boolean }) => void = () => {};
    const onRunSchedule = vi.fn().mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const { container, hover, unmount } = mountSchedule({ onRunSchedule });
    hover();
    act(() => { runButtonOf(container)!.click(); });
    const row = container.querySelector<HTMLElement>('.sidebar-row')!;
    act(() => { row.dispatchEvent(new MouseEvent('mouseout', { bubbles: true })); });
    const button = runButtonOf(container)!;
    expect(button.disabled).toBe(true);
    expect(container.querySelector('[role="status"]')!.textContent).toBe('Starting run…');
    act(() => button.click());
    expect(onRunSchedule).toHaveBeenCalledTimes(1);
    await act(async () => { finish({ ok: true }); });
    expect(container.querySelector('[role="status"]')!.textContent).toBe('Run started');
    unmount();
  });

  it('puts the schedule line back after the result has been shown', async () => {
    vi.useFakeTimers();
    try {
      const onRunSchedule = vi.fn().mockResolvedValue({ ok: true });
      const { container, hover, unmount } = mountSchedule({ onRunSchedule, preview: 'Recurring • next tomorrow' });
      hover();
      await act(async () => { runButtonOf(container)!.click(); });
      expect(container.querySelector('[role="status"]')).not.toBeNull();
      await act(async () => { vi.advanceTimersByTime(3100); });
      expect(container.querySelector('[role="status"]')).toBeNull();
      expect(container.textContent).toContain('Recurring • next tomorrow');
      unmount();
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps the activate switch and Run now independent of each other', async () => {
    const onToggleSchedule = vi.fn();
    const onRunSchedule = vi.fn().mockResolvedValue({ ok: true });
    const { container, hover, unmount } = mountSchedule({ scheduleActive: false, onToggleSchedule, onRunSchedule });
    hover();
    await act(async () => { runButtonOf(container)!.click(); });
    expect(onRunSchedule).toHaveBeenCalledTimes(1);
    expect(onToggleSchedule).not.toHaveBeenCalled();
    act(() => switchOf(container)!.click());
    expect(onToggleSchedule).toHaveBeenCalledWith('schedule-1', true);
    expect(onRunSchedule).toHaveBeenCalledTimes(1);
    unmount();
  });
});

