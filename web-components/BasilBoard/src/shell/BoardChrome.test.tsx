import { fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import type { BasilBoardTab } from '../contracts';
import { settleHostWindowResize } from '@shared/settleHostWindowResize';
import BoardChrome from './BoardChrome';

vi.mock('@shared/bubble/AnimatedBubble', () => ({
  default: () => <div data-testid="animated-bubble" />,
}));

const bridgeMocks = vi.hoisted(() => ({
  detachBasilBoardTab: vi.fn(),
  openNativeBasilBoardTabWindow: vi.fn(),
  reportBoardChromeGeometry: vi.fn(),
  requestWindowClose: vi.fn(),
  requestWindowCollapse: vi.fn(),
  requestWindowExpand: vi.fn(),
  requestWindowMinimize: vi.fn(),
}));

vi.mock('../services/bridge', () => bridgeMocks);

const shellCss = readFileSync('src/styles/shell.css', 'utf8');

const tabs: BasilBoardTab[] = [
  { id: 'home', title: 'Home', icon_key: 'home', position: 0, tab_kind: 'home', status: 'active', configuration: {} },
  { id: 'chats', title: 'Chats', icon_key: 'chat', position: 1, tab_kind: 'capability', status: 'active', configuration: {} },
  { id: 'meetings', title: 'Meetings', icon_key: 'meetings', position: 2, tab_kind: 'capability', status: 'active', configuration: {} },
];

describe('BoardChrome', () => {
  it('renders distinct known tab glyphs and preserves accessible selection', () => {
    const onSelectTab = (tabId: string) => {
      rerender(<BoardChrome tabs={tabs} activeTabId={tabId} onSelectTab={onSelectTab}><div>Content</div></BoardChrome>);
    };
    const { rerender } = render(
      <BoardChrome tabs={tabs} activeTabId="home" onSelectTab={onSelectTab}>
        <div>Content</div>
      </BoardChrome>,
    );

    const home = screen.getByRole('button', { name: 'Home' });
    const chats = screen.getByRole('button', { name: 'Chats' });
    const meetings = screen.getByRole('button', { name: 'Meetings' });

    expect(home.getAttribute('aria-current')).toBe('page');
    expect(home.querySelector('path')?.getAttribute('d')).toContain('M2.5 7.6');
    expect(chats.querySelector('path')?.getAttribute('d')).toContain('M4.7 2.8');
    expect(meetings.querySelector('rect')?.getAttribute('y')).toBe('3.5');

    fireEvent.click(chats);
    expect(chats.getAttribute('aria-current')).toBe('page');
    expect(home.getAttribute('aria-current')).toBeNull();
  });

  describe('tab badges', () => {
    const tabsWithTodos: BasilBoardTab[] = [
      ...tabs,
      { id: 'todos', title: 'To-Dos', icon_key: 'checklist', position: 3, tab_kind: 'capability', status: 'active', configuration: {} },
    ];

    it('shows total, due-today, and overdue pills beside the To-Dos icon without renaming the tab button', () => {
      const { container } = render(
        <BoardChrome
          tabs={tabsWithTodos}
          activeTabId="home"
          onSelectTab={() => {}}
          tabBadges={{ todos: { total: 12, due_today: 3, overdue: 2 } }}
        >
          <div>Content</div>
        </BoardChrome>,
      );
      expect(screen.getByRole('button', { name: 'To-Dos' })).toBeTruthy();
      const cluster = screen.getByRole('status', { name: '12 open, 3 due today, 2 overdue' });
      expect(cluster.textContent).toBe('1232');
      expect(cluster.querySelector('.basil-board-tab-badge--total')?.textContent).toBe('12');
      expect(cluster.querySelector('.basil-board-tab-badge--due-today')?.textContent).toBe('3');
      expect(cluster.querySelector('.basil-board-tab-badge--overdue')?.textContent).toBe('2');
      const slot = container.querySelector('.basil-board-tab-slot:has(button[aria-label="To-Dos"])');
      expect(slot?.contains(cluster)).toBe(true);
      expect(container.querySelectorAll('.basil-board-tab-badges')).toHaveLength(1);
    });

    it('hides the due-today and overdue pills at zero but always shows the total', () => {
      render(
        <BoardChrome
          tabs={tabsWithTodos}
          activeTabId="home"
          onSelectTab={() => {}}
          tabBadges={{ todos: { total: 0, due_today: 0, overdue: 0 } }}
        >
          <div>Content</div>
        </BoardChrome>,
      );
      const cluster = screen.getByRole('status', { name: '0 open' });
      expect(cluster.querySelectorAll('.basil-board-tab-badge')).toHaveLength(1);
      expect(cluster.textContent).toBe('0');
    });

    it('caps large counts and renders nothing before counts are known', () => {
      const { rerender, container } = render(
        <BoardChrome tabs={tabsWithTodos} activeTabId="home" onSelectTab={() => {}} tabBadges={{ todos: null }}>
          <div>Content</div>
        </BoardChrome>,
      );
      expect(container.querySelector('.basil-board-tab-badges')).toBeNull();
      rerender(
        <BoardChrome
          tabs={tabsWithTodos}
          activeTabId="home"
          onSelectTab={() => {}}
          tabBadges={{ todos: { total: 250, due_today: 0, overdue: 100 } }}
        >
          <div>Content</div>
        </BoardChrome>,
      );
      const cluster = screen.getByRole('status', { name: '250 open, 100 overdue' });
      expect(cluster.textContent).toBe('99+99+');
      expect(cluster.querySelectorAll('.basil-board-tab-badge--wide')).toHaveLength(2);
    });

    it('uses semantic color tokens, draws round badges, and leaves the rail width unchanged', () => {
      expect(shellCss).toMatch(/\.basil-board-tabs \{[\s\S]*?flex: 0 0 52px;/);
      expect(shellCss).toMatch(/\.basil-board-tab-badges \{[\s\S]*?position: absolute;/);
      const badge = /\.basil-board-tab-badge \{([^}]*)\}/.exec(shellCss)?.[1] ?? '';
      expect(badge).toContain('border-radius: 50%');
      expect(badge).toMatch(/width: calc\(14px \* var\(--text-scale, 1\)\)/);
      expect(badge).toMatch(/height: calc\(14px \* var\(--text-scale, 1\)\)/);
      expect(shellCss).toMatch(/\.basil-board-tab-badge--total \{[\s\S]*?background: var\(--primary\);/);
      expect(shellCss).toMatch(/\.basil-board-tab-badge--due-today \{[\s\S]*?var\(--warning-base/);
      expect(shellCss).toMatch(/\.basil-board-tab-badge--overdue \{[\s\S]*?var\(--error-base/);
    });
  });

  it('defines a complete active-tab border without changing tab dimensions', () => {
    expect(shellCss).toContain('width: 36px;');
    expect(shellCss).toContain('height: 36px;');
    expect(shellCss).toMatch(/\.basil-board-tab \{[\s\S]*box-sizing: border-box;[\s\S]*border: 1px solid transparent;/);
    expect(shellCss).toMatch(/\.basil-board-tab\.is-active \{[\s\S]*border-color: var\(--secondary\);/);
    expect(shellCss).not.toContain('border-left-color: var(--secondary);');
  });

  it('anchors window controls independently from the title stack height', () => {
    expect(shellCss).toMatch(/\.basil-board-header-left \{[\s\S]*align-items: flex-start;/);
    expect(shellCss).toMatch(/\.basil-board-window-controls \{[\s\S]*align-self: flex-start;/);
    expect(shellCss).toMatch(/\.basil-board-header-left > \.basil-board-window-controls \{[\s\S]*padding-top: 3px;/);
  });

  it('renders a distinct Agent Tasks glyph', () => {
    const tabsWithAgentTasks: BasilBoardTab[] = [
      ...tabs,
      { id: 'agent_tasks', title: 'Agent Tasks', icon_key: 'agent_tasks', position: 3, tab_kind: 'capability', status: 'active', configuration: {} },
    ];
    render(
      <BoardChrome tabs={tabsWithAgentTasks} activeTabId="home" onSelectTab={() => {}}>
        <div>Content</div>
      </BoardChrome>,
    );
    const agentTasks = screen.getByRole('button', { name: 'Agent Tasks' });
    expect(agentTasks.querySelector('rect')?.getAttribute('y')).toBe('5.5');
    expect(agentTasks.querySelector('path')?.getAttribute('d')).toContain('M8 5.5V3.4');
    expect(agentTasks.querySelectorAll('circle')).toHaveLength(3);
  });

  it('renders one native-window action for Agent Tasks and bypasses Board detachment', () => {
    const tabsWithAgentTasks: BasilBoardTab[] = [
      ...tabs,
      {
        id: 'agent_tasks',
        title: 'Agent Tasks',
        icon_key: 'agent_tasks',
        position: 3,
        tab_kind: 'capability',
        status: 'active',
        configuration: { detach_behavior: 'useNativeWindow' },
      },
    ];
    render(
      <BoardChrome
        tabs={tabsWithAgentTasks}
        activeTabId="agent_tasks"
        activeTabDetachBehavior="useNativeWindow"
        onSelectTab={() => {}}
      >
        <div>Content</div>
      </BoardChrome>,
    );

    const buttons = screen.getAllByRole('button', { name: 'Open Agent Tasks in a separate window' });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(bridgeMocks.openNativeBasilBoardTabWindow).toHaveBeenCalledWith('agent_tasks');
    expect(bridgeMocks.detachBasilBoardTab).not.toHaveBeenCalled();
  });

  it('routes useBoardWindow tabs through detachBasilBoardTab', () => {
    render(
      <BoardChrome
        tabs={tabs}
        activeTabId="chats"
        activeTabDetachBehavior="useBoardWindow"
        onSelectTab={() => {}}
      >
        <div>Content</div>
      </BoardChrome>,
    );

    const button = screen.getByRole('button', { name: 'Open Chats in a separate window' });
    fireEvent.click(button);
    expect(bridgeMocks.detachBasilBoardTab).toHaveBeenCalledWith('chats');
    expect(bridgeMocks.openNativeBasilBoardTabWindow).not.toHaveBeenCalled();
  });

  it('wraps the board shell in the shared WebKit window chrome contract', () => {
    const { container } = render(
      <BoardChrome tabs={tabs} activeTabId="home" onSelectTab={() => {}}>
        <div>Content</div>
      </BoardChrome>,
    );

    const frames = container.querySelectorAll('.basil-webkit-window-frame');
    expect(frames).toHaveLength(1);
    expect(frames[0]?.querySelector('.basil-board-root.basil-webkit-window-surface')).toBeTruthy();
  });

  it('retains mounted Board content while requesting native collapse and expansion', async () => {
    const { container } = render(
      <BoardChrome tabs={tabs} activeTabId="home" onSelectTab={() => {}}>
        <div>Board workspace content</div>
      </BoardChrome>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(bridgeMocks.requestWindowCollapse).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Board workspace content')).toBeTruthy();
    expect(container.querySelector('.basil-board-root')?.classList.contains('is-collapsed')).toBe(true);
    expect(container.querySelector('.basil-board-body')?.classList.contains('is-collapsed')).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    expect(bridgeMocks.requestWindowExpand).toHaveBeenCalledTimes(1);
    expect(container.querySelector('.basil-board-body')?.classList.contains('is-collapsed')).toBe(true);
    await settleHostWindowResize();
    expect(container.querySelector('.basil-board-root')?.classList.contains('is-collapsed')).toBe(false);
    expect(container.querySelector('.basil-board-body')?.classList.contains('is-collapsed')).toBe(false);
  });
});
