// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExecutionApprovalRequest } from '../../types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock('../../services/api', () => ({
  submitApprovalDecision: vi.fn(),
  submitBrowserSensitiveFillApproval: vi.fn(),
  submitProviderPermissionDecision: vi.fn(),
  submitSettingsChangeApproval: vi.fn(),
}));

vi.mock('../../store/agentStore', () => ({
  agentStore: {
    hideApproval: vi.fn(),
    removeApproval: vi.fn(),
    updateStatus: vi.fn(),
    updateProgressStep: vi.fn(),
    setError: vi.fn(),
    getActiveFollowUpId: vi.fn(),
  },
}));

let ApprovalSetOverlay: typeof import('./ApprovalSetOverlay').default;

beforeAll(async () => {
  ApprovalSetOverlay = (await import('./ApprovalSetOverlay')).default;
});

const shellApproval: ExecutionApprovalRequest = {
  approval_id: 'approval-shell',
  agent_task_id: 'task-1',
  command: 'ls -la\nsecond line',
  reason: 'Command not in whitelist',
  risk_level: 'low',
  execution_type: 'shell',
};

const secondApproval: ExecutionApprovalRequest = { ...shellApproval, approval_id: 'approval-shell-2', command: 'mdfind Calls_Meetings' };

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

function render(approvals: ExecutionApprovalRequest[], onStopTask?: () => void, isStopping = false) {
  act(() => {
    root.render(
      <ApprovalSetOverlay
        agentTaskId="task-1"
        approvals={approvals}
        rememberChoice={false}
        onStopTask={onStopTask}
        isStopping={isStopping}
      />,
    );
  });
}

function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll('button')).find(candidate => candidate.textContent === label);
  if (!match) throw new Error(`No button labeled ${label}`);
  return match;
}

function click(label: string) {
  act(() => button(label).click());
}

/** The labels of the decision buttons, in order. Other buttons, such as the link that expands a long command, are not decisions. */
function labels(): Array<string | null> {
  return Array.from(container.querySelectorAll('.decision-btn')).map(candidate => candidate.textContent);
}

function typeNote(text: string) {
  if (!container.querySelector('textarea.approval-note-input')) {
    act(() => container.querySelector<HTMLButtonElement>('.approval-note-toggle')?.click());
  }
  const textarea = container.querySelector('textarea.approval-note-input') as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
  act(() => {
    setter?.call(textarea, text);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('single approval controls', () => {
  it('offers the work-review and stop buttons beside Deny and Approve, all as one kind of button', () => {
    render([shellApproval], vi.fn());

    expect(labels()).toEqual(['See work so far', 'Stop task', 'Deny', 'Approve']);
    const classes = Array.from(container.querySelectorAll('.approval-actions button')).map(candidate => candidate.className);
    expect(classes).toHaveLength(4);
    classes.forEach(className => expect(className).toContain('decision-btn '));
    expect(container.querySelectorAll('.approval-actions .decision-btn__icon svg')).toHaveLength(4);
  });

  it('leaves the stop button out when the host gives no way to stop the task', () => {
    render([shellApproval]);

    expect(labels()).toEqual(['See work so far', 'Deny', 'Approve']);
  });

  it('stops the task with the host action, and names and disables the button while stopping', () => {
    const onStopTask = vi.fn();
    render([shellApproval], onStopTask);
    click('Stop task');
    expect(onStopTask).toHaveBeenCalledTimes(1);

    render([shellApproval], onStopTask, true);
    expect(button('Stopping').disabled).toBe(true);
  });
});

describe('the order is the same on every approval surface', () => {
  const orderOf = (labelsInRow: Array<string | null>) => ({
    tools: labelsInRow.filter(label => label === 'See work so far' || label === 'Stop task'),
    decisions: labelsInRow.filter(label => label === 'Deny' || label === 'Approve'),
  });

  it('puts the work review before Stop task, then Deny before Approve, on the single card', () => {
    render([shellApproval], vi.fn());
    const all = labels();
    expect(orderOf(all)).toEqual({ tools: ['See work so far', 'Stop task'], decisions: ['Deny', 'Approve'] });
    expect(all.indexOf('Stop task')).toBeLessThan(all.indexOf('Deny'));
  });

  it('keeps the same tools-then-decisions order for a stack, per item and in the shared row', () => {
    render([shellApproval, secondApproval], vi.fn());
    const footer = Array.from(container.querySelectorAll('.approval-set-footer .decision-btn')).map(button => button.textContent);
    expect(footer).toEqual(['See work so far', 'Stop task']);
    const lead = Array.from(container.querySelectorAll('.approval-set-footer .decision-btn--lead')).map(button => button.textContent);
    expect(lead).toEqual(['Stop task']);
  });

  it('ends the docked bar with the way back, with Stop task before it', () => {
    render([shellApproval], vi.fn());
    click('See work so far');
    const dockLabels = Array.from(container.querySelectorAll('.approval-dock .decision-btn')).map(button => button.textContent);
    expect(dockLabels).toEqual(['Stop task', 'Review now']);
  });
});

describe('a stack of approvals keeps its button row outside the scrolling area', () => {
  it('scrolls only the list, so nothing can show below the shared button row', () => {
    render([shellApproval, secondApproval], vi.fn());

    const frame = container.querySelector<HTMLElement>('.approval-set-frame');
    const scroller = container.querySelector<HTMLElement>('.approval-set-scroller');
    const footer = container.querySelector<HTMLElement>('.approval-set-footer');
    expect(frame).not.toBeNull();
    expect(scroller).not.toBeNull();
    expect(footer).not.toBeNull();

    expect(scroller?.querySelectorAll('.approval-set-card')).toHaveLength(2);
    expect(scroller?.contains(footer as HTMLElement)).toBe(false);
    expect(footer?.parentElement).toBe(frame);
    expect(frame?.lastElementChild).toBe(footer);
  });
});

describe('docking a single approval', () => {
  it('docks to a slim bar that summarizes the command, and keeps the approval mounted and hidden', () => {
    render([shellApproval], vi.fn());
    click('See work so far');

    const dock = container.querySelector<HTMLElement>('.approval-dock');
    expect(dock).not.toBeNull();
    expect(dock?.getAttribute('role')).toBe('region');
    expect(dock?.querySelector('.approval-dock__eyebrow')?.textContent).toBe('Approval required');
    expect(dock?.querySelector('.approval-dock__summary')?.textContent).toBe('ls -la');
    expect(Array.from(dock?.querySelectorAll('button') ?? []).map(candidate => candidate.textContent)).toEqual(['Stop task', 'Review now']);
    expect(container.querySelector('.overlay-backdrop--docked')).not.toBeNull();
    const fullApproval = container.querySelector<HTMLElement>('.overlay-card')?.closest('[hidden]');
    expect(fullApproval).not.toBeNull();
  });

  it('keeps a typed note through the round trip, and Review now brings the approval back', () => {
    render([shellApproval], vi.fn());
    typeNote('That file is in ~/Documents.');
    click('See work so far');
    click('Review now');

    expect(container.querySelector('.approval-dock')).toBeNull();
    expect(container.querySelector('.overlay-card')?.closest('[hidden]')).toBeNull();
    expect((container.querySelector('textarea.approval-note-input') as HTMLTextAreaElement).value).toBe('That file is in ~/Documents.');
  });

  it('stops the task from the dock too', () => {
    const onStopTask = vi.fn();
    render([shellApproval], onStopTask);
    click('See work so far');
    act(() => (container.querySelector('.approval-dock') as HTMLElement).querySelectorAll('button')[0].click());

    expect(onStopTask).toHaveBeenCalledTimes(1);
  });

  it('brings a different approval back at once instead of leaving it behind the bar', () => {
    render([shellApproval], vi.fn());
    click('See work so far');
    expect(container.querySelector('.approval-dock')).not.toBeNull();

    render([secondApproval], vi.fn());

    expect(container.querySelector('.approval-dock')).toBeNull();
    expect(container.querySelector('.overlay-card')?.closest('[hidden]')).toBeNull();
    expect(container.textContent).toContain('mdfind Calls_Meetings');
  });
});

describe('a stack of several approvals', () => {
  it('shows one shared row with the work-review and stop buttons, and Deny and Approve for each item', () => {
    render([shellApproval, secondApproval], vi.fn());

    expect(labels()).toEqual(['Deny', 'Approve', 'Deny', 'Approve', 'See work so far', 'Stop task']);
    expect(container.querySelectorAll('.approval-set-footer button')).toHaveLength(2);
  });

  it('docks the whole stack with a count, and restores it', () => {
    render([shellApproval, secondApproval], vi.fn());
    click('See work so far');

    const dock = container.querySelector<HTMLElement>('.approval-dock');
    expect(dock?.querySelector('.approval-dock__eyebrow')?.textContent).toBe('2 approvals required');
    expect(dock?.querySelector('.approval-dock__summary')?.textContent).toBe('2 requests are waiting for your decision');
    expect(container.querySelector('.overlay-backdrop[hidden]')).not.toBeNull();

    click('Review now');
    expect(container.querySelector('.approval-dock')).toBeNull();
    expect(container.querySelector('.overlay-backdrop[hidden]')).toBeNull();
  });
});
