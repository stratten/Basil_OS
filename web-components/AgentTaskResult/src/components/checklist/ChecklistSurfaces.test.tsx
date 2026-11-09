// @vitest-environment jsdom

import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { WSEvent } from '../../types';
import { makeChecklistItem, makeChecklistSnapshot } from './checklistTestData';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const api = vi.hoisted(() => ({
  getChecklist: vi.fn(),
  getChecklistItemLog: vi.fn(),
  addChecklistItem: vi.fn(),
  updateChecklistItem: vi.fn(),
  archiveChecklistItem: vi.fn(),
  closeChecklist: vi.fn(),
  saveChecklistNotes: vi.fn(),
  offerChecklistItemAsTodo: vi.fn(),
}));
vi.mock('../../services/api', () => ({ isApiReady: () => true }));
vi.mock('../../services/checklistApi', () => ({
  ...api,
  isChecklistConflict: (error: unknown) => error instanceof Error && /\(409\)$/.test(error.message),
}));
vi.mock('../../services/websocket', () => ({
  wsManager: { subscribe: () => () => {}, onConnect: () => () => {} } satisfies { subscribe: (handler: (event: WSEvent) => void) => () => void; onConnect: (handler: () => void) => () => void },
}));

import ChecklistOverviewSection from './ChecklistOverviewSection';
import ChecklistRailPill from './ChecklistRailPill';
import ChecklistWindow from './ChecklistWindow';
import { resetChecklistStoreForTests } from '../../store/checklistStore';
import { openChecklistWindow, resetChecklistViewForTests, useChecklistWindowRoot } from '../../store/checklistViewStore';

function ViewProbe() {
  const windowRoot = useChecklistWindowRoot();
  return <output data-testid="view">{windowRoot ?? 'no-window'}</output>;
}

describe('checklist surfaces', () => {
  let container: HTMLDivElement;
  let root: Root;
  const onNavigateRun = vi.fn();

  beforeEach(() => {
    resetChecklistStoreForTests();
    resetChecklistViewForTests();
    Object.values(api).forEach(mock => mock.mockReset());
    api.getChecklistItemLog.mockResolvedValue({ item_id: 'item-1', events: [], captured: [] });
    onNavigateRun.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (node: React.ReactNode) => {
    await act(async () => { root.render(node); });
  };
  const q = <T extends Element>(selector: string) => container.querySelector(selector) as T;
  const byLabel = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLElement;
  const click = async (element: Element) => {
    await act(async () => { (element as HTMLElement).click(); });
  };
  const showMoreDetails = async () => {
    await click(Array.from(container.querySelectorAll('.checklist-detail__actions button')).find(node => node.textContent === 'Edit details and history')!);
  };
  const type = async (element: HTMLInputElement | HTMLTextAreaElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), 'value')!.set!;
    await act(async () => {
      setter.call(element, value);
      element.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
  const blur = async (element: Element) => {
    await act(async () => { element.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); });
  };
  const three = () => makeChecklistSnapshot([
    makeChecklistItem({ id: 'a', title: 'Book a GP visit', status: 'pending', sort_order: 0 }),
    makeChecklistItem({ id: 'b', title: 'Choose a time', status: 'waiting_user', waiting_on: 'Your calendar', sort_order: 1, revision: 3 }),
    makeChecklistItem({ id: 'c', title: 'Get a referral', status: 'done', sort_order: 2 }),
  ]);

  describe('rail pill', () => {
    it('renders nothing for a chain without items', async () => {
      api.getChecklist.mockResolvedValue(makeChecklistSnapshot([]));
      await render(<ChecklistRailPill rootTaskId="root-1" />);
      expect(q('.agent-run-rail-checklist')).toBeNull();
    });

    it('shows done over total, flags a wait on the reader, and opens the checklist window when pressed', async () => {
      api.getChecklist.mockResolvedValue(three());
      await render(<><ChecklistRailPill rootTaskId="root-1" /><ViewProbe /></>);

      const pill = q<HTMLButtonElement>('.agent-run-rail-checklist-pill');
      expect(pill.textContent).toBe('1/3');
      expect(pill.classList.contains('is-attention')).toBe(true);
      expect(pill.getAttribute('aria-label')).toBe('Checklist, 1 of 3 done, 1 needs your input. Open the checklist');
      expect(q('[data-testid="view"]').textContent).toBe('no-window');

      await click(pill);
      expect(q('[data-testid="view"]').textContent).toBe('root-1');
    });

    it('uses the complete tone when every item is done and the neutral tone otherwise', async () => {
      api.getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem({ status: 'done' })]));
      await render(<ChecklistRailPill rootTaskId="root-1" />);
      expect(q('.agent-run-rail-checklist-pill').classList.contains('is-complete')).toBe(true);

      resetChecklistStoreForTests();
      api.getChecklist.mockResolvedValue(makeChecklistSnapshot([makeChecklistItem({ status: 'pending' })]));
      await render(<ChecklistRailPill rootTaskId="root-2" />);
      expect(q('.agent-run-rail-checklist-pill').classList.contains('is-neutral')).toBe(true);
    });
  });

  describe('Run overview section', () => {
    it('renders nothing until the chain has items', async () => {
      api.getChecklist.mockResolvedValue(makeChecklistSnapshot([]));
      await render(<ChecklistOverviewSection rootTaskId="root-1" />);
      expect(q('.checklist-overview')).toBeNull();
    });

    it('reads "N of M done" and lists what needs the reader first, one line per item', async () => {
      api.getChecklist.mockResolvedValue(three());
      await render(<><ChecklistOverviewSection rootTaskId="root-1" /><ViewProbe /></>);

      const header = q('.checklist-overview__header');
      expect(header.textContent).toContain('Checklist');
      expect(header.textContent).toContain('1 of 3 done');
      expect(header.textContent).toContain('1 needs your input');
      const titles = Array.from(container.querySelectorAll('.checklist-overview__row-title')).map(node => node.textContent);
      expect(titles).toEqual(['Choose a time', 'Book a GP visit', 'Get a referral']);
      expect(q('.checklist-overview__row-sub').textContent).toBe('Your calendar');
      expect(q('.checklist-overview__open').textContent).toBe('Open checklist');

      await click(container.querySelectorAll<HTMLButtonElement>('.checklist-overview__row')[1]);
      expect(q('[data-testid="view"]').textContent).toBe('root-1');
    });

    it('caps the list at five rows and offers the full window for the rest', async () => {
      const many = Array.from({ length: 8 }, (_, index) => makeChecklistItem({ id: `m${index}`, title: `Step ${index}`, sort_order: index }));
      api.getChecklist.mockResolvedValue(makeChecklistSnapshot(many));
      await render(<><ChecklistOverviewSection rootTaskId="root-1" /><ViewProbe /></>);

      expect(container.querySelectorAll('.checklist-overview__rows li')).toHaveLength(5);
      const showAll = q<HTMLButtonElement>('.checklist-overview__open');
      expect(showAll.textContent).toBe('Show all 8');
      await click(showAll);
      expect(q('[data-testid="view"]').textContent).toBe('root-1');
    });
  });

  describe('window', () => {
    const mountWindow = async (snapshot = three(), props: Partial<React.ComponentProps<typeof ChecklistWindow>> = {}) => {
      api.getChecklist.mockResolvedValue(snapshot);
      await render(<><ChecklistWindow rootTaskId="root-1" onNavigateRun={onNavigateRun} {...props} /><ViewProbe /></>);
      await act(async () => { openChecklistWindow('root-1'); });
    };

    it('is closed until opened, and shows open items first with the reader-facing counter', async () => {
      api.getChecklist.mockResolvedValue(three());
      await render(<ChecklistWindow rootTaskId="root-1" />);
      expect(q('.checklist-window')).toBeNull();

      await act(async () => { openChecklistWindow('root-1'); });
      expect(q('.checklist-window').getAttribute('role')).toBe('dialog');
      expect(q('.checklist-window__count').textContent).toBe('1 of 3 done');
      expect(Array.from(container.querySelectorAll('.checklist-window__items .checklist-row__title')).map(node => node.textContent)).toEqual(['Choose a time', 'Book a GP visit']);
    });

    it('switches between open, all and archived items', async () => {
      await mountWindow(makeChecklistSnapshot([
        makeChecklistItem({ id: 'a', title: 'Open one' }),
        makeChecklistItem({ id: 'b', title: 'Finished one', status: 'done' }),
        makeChecklistItem({ id: 'c', title: 'Archived one', archived_at: '2026-11-03 10:00:00' }),
      ]));
      const titles = () => Array.from(container.querySelectorAll('.checklist-window__items .checklist-row__title')).map(node => node.textContent);
      const filter = (label: string) => Array.from(container.querySelectorAll('.checklist-filter')).find(node => node.textContent?.startsWith(label))!;

      expect(titles()).toEqual(['Open one']);
      await click(filter('All'));
      expect(titles()).toEqual(['Open one', 'Finished one']);
      await click(filter('Archived'));
      expect(titles()).toEqual(['Archived one']);
    });

    it('adds an item with the typed title trimmed, and shows a server refusal', async () => {
      await mountWindow();
      api.addChecklistItem.mockRejectedValueOnce(new Error('The checklist is full (409)'));
      const input = byLabel('New checklist item') as HTMLTextAreaElement;
      const add = () => Array.from(container.querySelectorAll('.checklist-add button')).find(node => node.textContent === 'Add') as HTMLButtonElement;

      expect(add().disabled).toBe(true);
      await type(input, '  Call the clinic  ');
      await click(add());
      expect(api.addChecklistItem).toHaveBeenCalledWith('root-1', { title: 'Call the clinic', required: false });
      expect(q('.checklist-add__error').textContent).toContain('The checklist is full');

      api.addChecklistItem.mockResolvedValueOnce({ created: true, duplicate: false, item: makeChecklistItem() });
      await click(add());
      expect(q('.checklist-add__error')).toBeNull();
      expect((byLabel('New checklist item') as HTMLTextAreaElement).value).toBe('');
    });

    it('takes a multi-line step in a text area and adds it with Command-Return', async () => {
      await mountWindow();
      api.addChecklistItem.mockResolvedValueOnce({ created: true, duplicate: false, item: makeChecklistItem() });
      const area = byLabel('New checklist item') as HTMLTextAreaElement;

      expect(area.tagName).toBe('TEXTAREA');
      expect(area.maxLength).toBe(500);
      await type(area, 'Call the clinic.\nAsk about Friday.');
      await act(async () => { area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true })); });

      expect(api.addChecklistItem).toHaveBeenCalledWith('root-1', { title: 'Call the clinic.\nAsk about Friday.', required: false });
      expect(area.value).toBe('');
    });

    it('does not add on a plain Enter, which starts a new line', async () => {
      await mountWindow();
      const area = byLabel('New checklist item') as HTMLTextAreaElement;

      await type(area, 'One line');
      await act(async () => { area.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })); });

      expect(api.addChecklistItem).not.toHaveBeenCalled();
    });

    it('opens an item from the Run overview already expanded, loads its step log, and links only http references', async () => {
      const snapshot = makeChecklistSnapshot([makeChecklistItem({
        id: 'a', title: 'Send the form', updated_by_task_id: 'turn-2',
        refs: [
          { id: 'r1', item_id: 'a', role: 'primary', ref_kind: 'gmail_thread', source_system: 'gmail', source_scope: '', external_id: 't-1', label: 'Insurer thread', open_url: 'https://mail.example/t-1', added_by: 'agent', last_known_status: null, last_known_at: null },
          { id: 'r2', item_id: 'a', role: 'related', ref_kind: 'file', source_system: 'files', source_scope: '', external_id: 'f', label: 'Local form', open_url: 'javascript:alert(1)', added_by: 'agent', last_known_status: null, last_known_at: null },
        ],
      })]);
      api.getChecklistItemLog.mockResolvedValue({
        item_id: 'a',
        events: [{ id: 'e1', item_id: 'a', agent_task_id: 'turn-2', kind: 'status', actor: 'agent', text: 'pending to in_progress', created_at: 'x' }],
        captured: [{ service: 'email_service', method: 'send_email', execution_state: 'succeeded', verification_status: 'verified', material_write: true, created_at: 'x' }],
      });
      api.getChecklist.mockResolvedValue(snapshot);
      await render(<ChecklistWindow rootTaskId="root-1" onNavigateRun={onNavigateRun} />);
      await act(async () => { openChecklistWindow('root-1', 'a'); });

      expect(q('.checklist-detail')).not.toBeNull();
      expect(q('.checklist-log')).toBeNull();
      await showMoreDetails();
      expect(api.getChecklistItemLog).toHaveBeenCalledWith('root-1', 'a');
      expect(q('.checklist-log').textContent).toContain('Changed status: to do to in progress');
      expect(container.textContent).toContain('email_service.send_email: succeeded, verified');
      const links = Array.from(container.querySelectorAll('.checklist-refs a')).map(node => node.getAttribute('href'));
      expect(links).toEqual(['https://mail.example/t-1']);
      expect(container.textContent).toContain('Local form');

      const runLink = Array.from(container.querySelectorAll('.checklist-detail__actions button')).find(node => node.textContent?.startsWith('Go to the run'))!;
      await click(runLink);
      expect(onNavigateRun).toHaveBeenCalledWith('turn-2');
      expect(q('.checklist-window')).toBeNull();
    });

    it('saves an edited title against the revision it was loaded at, and a blank title is restored instead of sent', async () => {
      await mountWindow(three());
      await act(async () => { openChecklistWindow('root-1', 'b'); });
      await showMoreDetails();
      api.updateChecklistItem.mockResolvedValue({ item: makeChecklistItem(), changed: true });
      const title = () => q<HTMLInputElement>('#checklist-b-title');

      await type(title(), 'Choose a visit time');
      await blur(title());
      expect(api.updateChecklistItem).toHaveBeenCalledWith('root-1', 'b', { title: 'Choose a visit time', expected_revision: 3 });

      api.updateChecklistItem.mockClear();
      await type(title(), '   ');
      await blur(title());
      expect(api.updateChecklistItem).not.toHaveBeenCalled();
    });

    it('explains a revision conflict, reloads the latest list, and keeps what was typed', async () => {
      await mountWindow(three());
      await act(async () => { openChecklistWindow('root-1', 'b'); });
      await showMoreDetails();
      api.updateChecklistItem.mockRejectedValue(new Error('This changed while you were editing it (409)'));
      api.getChecklist.mockClear();
      const detail = q<HTMLTextAreaElement>('#checklist-b-detail');

      await type(detail, 'Prefer mornings');
      await blur(detail);

      expect(q('.checklist-window__message').textContent).toContain('anything you typed is kept');
      expect(api.getChecklist).toHaveBeenCalledTimes(1);
      expect(q<HTMLTextAreaElement>('#checklist-b-detail').value).toBe('Prefer mornings');
    });

    it('marks an item required immediately and offers only waiting-on-you items as a To-Do', async () => {
      await mountWindow(three());
      await act(async () => { openChecklistWindow('root-1', 'b'); });
      api.updateChecklistItem.mockResolvedValue({ item: makeChecklistItem(), changed: true });
      api.offerChecklistItemAsTodo.mockResolvedValue({ todo_id: 't1', status: 'candidate' });

      await click(q('.checklist-detail .checklist-detail__required input'));
      expect(api.updateChecklistItem).toHaveBeenCalledWith('root-1', 'b', { required: true, expected_revision: 3 });

      const offer = Array.from(container.querySelectorAll('.checklist-detail__actions button')).find(node => node.textContent === 'Offer as a To-Do') as HTMLButtonElement;
      await click(offer);
      expect(api.offerChecklistItemAsTodo).toHaveBeenCalledWith('root-1', 'b');
      expect(q('.checklist-window__panel [role="status"]').textContent).toContain('Offered as a To-Do');

      await act(async () => { openChecklistWindow('root-1', 'a'); });
      expect(Array.from(container.querySelectorAll('.checklist-detail__actions button')).some(node => node.textContent === 'Offer as a To-Do')).toBe(false);
    });

    it('archives from the detail and stops or resumes tracking from the footer', async () => {
      await mountWindow(three());
      await act(async () => { openChecklistWindow('root-1', 'a'); });
      api.archiveChecklistItem.mockResolvedValue({ item: makeChecklistItem() });
      api.closeChecklist.mockResolvedValue({ closed_at: '2026-11-03 11:00:00' });

      await click(Array.from(container.querySelectorAll('.checklist-detail__actions button')).find(node => node.textContent === 'Archive')!);
      expect(api.archiveChecklistItem).toHaveBeenCalledWith('root-1', 'a', true);

      expect(Array.from(container.querySelectorAll('.checklist-window__header-actions button')).map(node => node.textContent)).toEqual(['Close window']);
      await click(Array.from(container.querySelectorAll('.checklist-window__footer button')).find(node => node.textContent === 'Stop tracking')!);
      expect(api.closeChecklist).toHaveBeenCalledWith('root-1', true);
    });

    it('edits the notes with a live character budget and refuses to save past the cap', async () => {
      await mountWindow(makeChecklistSnapshot([makeChecklistItem()], { notes: { content: 'Clinic answers Fridays.', revision: 2, updated_by: 'agent', updated_at: 'x', carried_from_task_id: null }, notes_max_chars: 50 }));
      await click(q('#checklist-tab-notes'));
      api.saveChecklistNotes.mockResolvedValue({ notes: {} });
      const area = q<HTMLTextAreaElement>('#checklist-notes-text');
      const save = () => Array.from(container.querySelectorAll('.checklist-notes button')).find(node => node.textContent === 'Save notes') as HTMLButtonElement;

      expect(area.value).toBe('Clinic answers Fridays.');
      expect(q('.checklist-notes__status').textContent).toBe('Last edited by Basil.');
      expect(save().disabled).toBe(true);

      await type(area, 'x'.repeat(60));
      expect(q('.checklist-notes__count').textContent).toContain('10 characters over the 50 limit');
      expect(save().disabled).toBe(true);

      await type(area, 'Clinic answers Mondays.');
      await click(save());
      expect(api.saveChecklistNotes).toHaveBeenCalledWith('root-1', 'Clinic answers Mondays.', 2);
    });

    it('labels notes carried from a previous run, and explains a notes conflict without discarding the text', async () => {
      await mountWindow(makeChecklistSnapshot([makeChecklistItem()], { notes: { content: 'Old state', revision: 1, updated_by: 'system', updated_at: 'x', carried_from_task_id: 'prev' } }));
      await click(q('#checklist-tab-notes'));
      expect(q('.checklist-notes__status').textContent).toContain('Carried from the previous run');

      api.saveChecklistNotes.mockRejectedValue(new Error('This changed (409)'));
      await type(q<HTMLTextAreaElement>('#checklist-notes-text'), 'My version');
      await click(Array.from(container.querySelectorAll('.checklist-notes button')).find(node => node.textContent === 'Save notes')!);
      expect(q('.checklist-notes__message').textContent).toContain('Save again to replace them');
      expect(q<HTMLTextAreaElement>('#checklist-notes-text').value).toBe('My version');
    });

    it('closes on Escape and on the backdrop, and steps aside without unmounting while an approval is showing', async () => {
      await mountWindow();
      expect(q('.checklist-window-region').hasAttribute('hidden')).toBe(false);

      await render(<><ChecklistWindow rootTaskId="root-1" yielding /><ViewProbe /></>);
      expect(q('.checklist-window-region').hasAttribute('hidden')).toBe(true);
      expect(q('.checklist-window')).not.toBeNull();

      await render(<><ChecklistWindow rootTaskId="root-1" /><ViewProbe /></>);
      await act(async () => { q('.checklist-window').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); });
      expect(q('.checklist-window')).toBeNull();

      await act(async () => { openChecklistWindow('root-1'); });
      await click(q('.checklist-window-backdrop'));
      expect(q('.checklist-window')).toBeNull();
    });

    it('shows loading, error with retry, and the empty state with the add form', async () => {
      let release: (value: unknown) => void = () => {};
      api.getChecklist.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
      await render(<ChecklistWindow rootTaskId="root-1" />);
      await act(async () => { openChecklistWindow('root-1'); });
      expect(q('.checklist-window__quiet').textContent).toContain('Loading the checklist');

      await act(async () => { release(makeChecklistSnapshot([])); });
      expect(container.textContent).toContain('No items yet');
      expect(byLabel('New checklist item')).not.toBeNull();
    });

    it('offers a retry when the first load fails', async () => {
      api.getChecklist.mockRejectedValueOnce(new Error('backend unavailable'));
      await render(<ChecklistWindow rootTaskId="root-1" />);
      await act(async () => { openChecklistWindow('root-1'); });
      expect(q('.checklist-window__failure').textContent).toContain('backend unavailable');

      api.getChecklist.mockResolvedValue(three());
      await click(q('.checklist-window__failure button'));
      expect(q('.checklist-window__items')).not.toBeNull();
    });
  });
});
