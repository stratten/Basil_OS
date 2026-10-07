import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ConversationWindowChrome from './ConversationWindowChrome';

let simulatedViewportHeight = 560;

function simulateHostWindowResize() {
  simulatedViewportHeight += 40;
  Object.defineProperty(window, 'innerHeight', { configurable: true, value: simulatedViewportHeight });
  window.dispatchEvent(new Event('resize'));
}

async function expandAndSettle(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Expand' }));
  simulateHostWindowResize();
  await waitFor(() => {
    expect(document.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(false);
  });
}

const bridgeMocks = vi.hoisted(() => ({
  requestWindowClose: vi.fn(),
  requestWindowMinimize: vi.fn(),
  requestWindowCollapse: vi.fn(),
  requestWindowExpand: vi.fn(),
}));
vi.mock('../services/bridge', () => bridgeMocks);

describe('ConversationWindowChrome', () => {
  it('renders the title, children, and wires close/minimize to the bridge', async () => {
    render(
      <ConversationWindowChrome>
        <div>Workspace content</div>
      </ConversationWindowChrome>,
    );
    expect(screen.getByText('Conversation')).toBeTruthy();
    expect(screen.getByText('Workspace content')).toBeTruthy();

    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(bridgeMocks.requestWindowClose).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: 'Minimize' }));
    expect(bridgeMocks.requestWindowMinimize).toHaveBeenCalledTimes(1);
  });

  it('collapses visually while retaining children and toggling the bridge message', async () => {
    const user = userEvent.setup();
    render(
      <ConversationWindowChrome>
        <div>Workspace content</div>
      </ConversationWindowChrome>,
    );

    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(bridgeMocks.requestWindowCollapse).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Workspace content')).toBeTruthy();
    expect(document.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(true);
    expect(document.querySelector('.conversation-window-collapse-chevron')?.classList.contains('is-collapsed')).toBe(true);

    await expandAndSettle(user);
    expect(bridgeMocks.requestWindowExpand).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Workspace content')).toBeTruthy();
    expect(document.querySelector('.conversation-window-collapse-chevron')?.classList.contains('is-collapsed')).toBe(false);
  });

  it('keeps the content collapsed while the window grows and reveals it after the resize settles', async () => {
    const user = userEvent.setup();
    render(
      <ConversationWindowChrome>
        <div>Workspace content</div>
      </ConversationWindowChrome>,
    );

    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    await user.click(screen.getByRole('button', { name: 'Expand' }));

    expect(bridgeMocks.requestWindowExpand).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Collapse' })).toHaveAttribute('aria-pressed', 'false');
    expect(document.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(true);
    expect(document.querySelector('.basil-board-content')).toHaveAttribute('inert');

    simulateHostWindowResize();
    await waitFor(() => {
      expect(document.querySelector('.basil-board-content')?.classList.contains('is-collapsed')).toBe(false);
    });
    expect(document.querySelector('.basil-board-content')).not.toHaveAttribute('inert');
  });

  it('retains an unsent entry draft across repeated collapse cycles', async () => {
    const user = userEvent.setup();
    render(
      <ConversationWindowChrome>
        <label>
          Message
          <input aria-label="Message" />
        </label>
      </ConversationWindowChrome>,
    );
    const input = screen.getByRole('textbox', { name: 'Message' }) as HTMLInputElement;
    await user.type(input, 'Detailed unsent conversation draft');

    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    const content = document.querySelector('.basil-board-content');
    expect(content).toHaveAttribute('aria-hidden', 'true');
    expect(content).toHaveAttribute('inert');

    await expandAndSettle(user);
    expect(screen.getByRole('textbox', { name: 'Message' })).toBe(input);
    expect(input.value).toBe('Detailed unsent conversation draft');

    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    await expandAndSettle(user);
    expect(input.value).toBe('Detailed unsent conversation draft');
  });

  it('renders the Conversation feature icon beside the title', () => {
    render(
      <ConversationWindowChrome subtitle="Selected conversation">
        <div>Workspace content</div>
      </ConversationWindowChrome>,
    );

    expect(document.querySelector('.conversation-window-feature-icon')).toBeTruthy();
    expect(screen.getByText('Selected conversation')).toBeTruthy();
  });

  it('uses the shared WebKit window chrome contract in expanded and collapsed states', async () => {
    render(
      <ConversationWindowChrome subtitle="Selected conversation">
        <div>Workspace content</div>
      </ConversationWindowChrome>,
    );

    const frame = document.querySelector('.basil-webkit-window-frame.conversation-standalone-frame');
    const shell = document.querySelector('.basil-board-root.basil-board-detached-shell.basil-webkit-window-surface');
    expect(frame).toBeTruthy();
    expect(shell).toBeTruthy();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(document.querySelector('.basil-webkit-window-frame.conversation-standalone-frame')).toBeTruthy();
    expect(document.querySelector('.basil-board-root.basil-board-detached-shell.basil-webkit-window-surface.is-collapsed')).toBeTruthy();

    await expandAndSettle(user);
    expect(document.querySelector('.basil-board-root.basil-board-detached-shell.basil-webkit-window-surface.is-collapsed')).toBeNull();
  });
});
