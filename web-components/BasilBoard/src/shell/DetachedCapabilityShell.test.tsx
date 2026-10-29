import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { BasilBoardTab } from '../contracts';
import { settleHostWindowResize } from '@shared/settleHostWindowResize';
import DetachedCapabilityShell from './DetachedCapabilityShell';

const bridgeMocks = vi.hoisted(() => ({
  requestWindowClose: vi.fn(),
  requestWindowCollapse: vi.fn(),
  requestWindowExpand: vi.fn(),
  requestWindowMinimize: vi.fn(),
}));

vi.mock('../services/bridge', () => bridgeMocks);
vi.mock('./TabRegistry', () => ({
  resolveTabRenderer: () => () => <div>To-Do workspace content</div>,
}));

const todoTab: BasilBoardTab = {
  id: 'todos',
  title: 'To-Dos',
  icon_key: 'checklist',
  position: 0,
  tab_kind: 'capability',
  status: 'active',
  configuration: { capability_id: 'todos.workspace' },
};

describe('DetachedCapabilityShell', () => {
  it('retains the capability content while requesting native collapse and expansion', async () => {
    const { container } = render(<DetachedCapabilityShell tabs={[todoTab]} detachedTabId="todos" />);

    expect(screen.getByText('To-Dos')).toBeTruthy();
    expect(screen.getByText('To-Do workspace content')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(bridgeMocks.requestWindowCollapse).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.basil-board-detached-shell')?.classList.contains('is-collapsed')).toBe(true);
    expect(container.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(true);
    expect(screen.getByText('To-Do workspace content')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    expect(bridgeMocks.requestWindowExpand).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(true);
    await settleHostWindowResize();
    expect(container.querySelector('.basil-board-detached-shell')?.classList.contains('is-collapsed')).toBe(false);
    expect(container.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(false);
  });
});
