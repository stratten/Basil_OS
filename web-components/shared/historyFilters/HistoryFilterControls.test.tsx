// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { describe, expect, it, vi } from 'vitest';
import { HistoryFilterButton, HistoryFilterPanel, type HistoryFilterField } from './HistoryFilterControls';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const rows: HistoryFilterField[][] = [
  [{ kind: 'select', key: 'status', label: 'Status', value: 'any', options: [{ value: 'any', label: 'Any status' }, { value: 'failed', label: 'Failed' }] }],
  [
    { kind: 'text', key: 'app', label: 'Application', value: '', placeholder: 'App' },
    { kind: 'select', key: 'length', label: 'Length', value: 'any', options: [{ value: 'any', label: 'Any' }] },
  ],
];

function mount(node: React.ReactElement) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => { root.render(node); });
  return { container, unmount: () => { act(() => { root.unmount(); }); container.remove(); } };
}

describe('HistoryFilterButton', () => {
  it('names the filters and shows a badge only when some are active', () => {
    const onToggle = vi.fn();
    const quiet = mount(<HistoryFilterButton activeCount={0} expanded={false} onToggle={onToggle} panelId="p" label="Chat filters" title="Filter chats" />);
    const idle = quiet.container.querySelector('button');
    expect(idle?.getAttribute('aria-label')).toBe('Chat filters');
    expect(idle?.querySelector('.sidebar-filter-badge')).toBeNull();
    act(() => { idle?.click(); });
    expect(onToggle).toHaveBeenCalledTimes(1);
    quiet.unmount();

    const busy = mount(<HistoryFilterButton activeCount={2} expanded panelId="p" onToggle={onToggle} label="Chat filters" title="Filter chats" />);
    const active = busy.container.querySelector('button');
    expect(active?.getAttribute('aria-label')).toBe('Chat filters, 2 active');
    expect(active?.getAttribute('aria-expanded')).toBe('true');
    expect(active?.querySelector('.sidebar-filter-badge')?.textContent).toBe('2');
    busy.unmount();
  });
});

describe('HistoryFilterPanel', () => {
  it('reports one-key changes for dates and text fields, keeps paired fields in one grid, and disables Clear when idle', () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    const view = mount(
      <HistoryFilterPanel panelId="p" label="Chat filters" expanded startDate={null} endDate={null} fieldRows={rows} activeCount={0} onChange={onChange} onClear={onClear} />,
    );
    expect(view.container.querySelectorAll('.sidebar-filter-grid')).toHaveLength(2);
    expect(view.container.querySelector<HTMLButtonElement>('.sidebar-filters-clear')?.disabled).toBe(true);

    const date = view.container.querySelector<HTMLInputElement>('input[type="date"]')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(date, '2026-03-05');
      date.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith({ startDate: '2026-03-05' });

    const text = view.container.querySelector<HTMLInputElement>('input[type="search"]')!;
    act(() => {
      setValue.call(text, 'Mail');
      text.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledWith({ app: 'Mail' });
    view.unmount();
  });

  it('enables Clear when filters are active', () => {
    const onClear = vi.fn();
    const view = mount(
      <HistoryFilterPanel panelId="p" label="Chat filters" expanded startDate="2026-03-01" endDate={null} fieldRows={rows} activeCount={1} onChange={() => {}} onClear={onClear} />,
    );
    act(() => { view.container.querySelector<HTMLButtonElement>('.sidebar-filters-clear')?.click(); });
    expect(onClear).toHaveBeenCalledTimes(1);
    view.unmount();
  });
});
