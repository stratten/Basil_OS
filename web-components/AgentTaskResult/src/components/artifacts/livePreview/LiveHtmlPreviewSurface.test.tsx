// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LiveHtmlPreviewSurface, type LiveHtmlPreviewSurfaceProps } from './LiveHtmlPreviewSurface';
import type { UseManagedVersionHistoryResult } from '../managedHistory/useManagedVersionHistory';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  container.remove();
});

function managed(overrides: Partial<UseManagedVersionHistoryResult['state']> = {}): UseManagedVersionHistoryResult {
  return {
    state: {
      status: 'idle',
      versions: [],
      selectedIndex: 0,
      restoreStatus: 'idle',
      ...overrides,
    },
    canRestore: false,
    selectVersion: vi.fn(),
    restore: vi.fn(),
    retry: vi.fn(),
  };
}

function baseProps(overrides: Partial<LiveHtmlPreviewSurfaceProps> = {}): LiveHtmlPreviewSurfaceProps {
  return {
    displayName: 'report.html',
    status: 'ready',
    statusText: 'Ready',
    renderedPreviewUrl: 'basil-inline-preview://local/tmp/report.html?basilPreviewRevision=0',
    targetUrl: 'basil-inline-preview://local/tmp/report.html',
    isHistorical: false,
    historicalViewMode: 'render',
    setHistoricalViewMode: vi.fn(),
    hasVersionHistory: false,
    canDiffHistorical: false,
    managed: managed(),
    needsLocalServer: false,
    serverForm: {
      command: '',
      args: '',
      cwd: '',
      port: 4173,
      setCommand: vi.fn(),
      setArgs: vi.fn(),
      setCwd: vi.fn(),
      setPort: vi.fn(),
    },
    isStartingServer: false,
    startServer: vi.fn(),
    stopServer: vi.fn(),
    refresh: vi.fn(),
    ...overrides,
  } as LiveHtmlPreviewSurfaceProps;
}

function render(props: LiveHtmlPreviewSurfaceProps) {
  const root = createRoot(container);
  act(() => {
    root.render(<LiveHtmlPreviewSurface {...props} />);
  });
  return { unmount: () => act(() => root.unmount()) };
}

describe('LiveHtmlPreviewSurface', () => {
  it('renders a scripted live iframe by default', () => {
    const view = render(baseProps());
    try {
      const frame = container.querySelector('iframe');
      expect(frame).not.toBeNull();
      expect(frame?.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin');
      expect(frame?.getAttribute('src')).toBe('basil-inline-preview://local/tmp/report.html?basilPreviewRevision=0');
    } finally {
      view.unmount();
    }
  });

  it('renders the local-server setup form when needsLocalServer is true', () => {
    const startServer = vi.fn();
    const view = render(baseProps({ needsLocalServer: true, startServer }));
    try {
      expect(container.querySelector('.local-web-preview-server-setup')).not.toBeNull();
      expect(container.querySelector('iframe')).toBeNull();
      const button = container.querySelector('.local-web-preview-start-action') as HTMLButtonElement | null;
      expect(button).not.toBeNull();
      act(() => button?.click());
      expect(startServer).toHaveBeenCalledTimes(1);
    } finally {
      view.unmount();
    }
  });

  it('renders a sandboxed static frame for an earlier historical version', () => {
    const view = render(baseProps({
      isHistorical: true,
      managed: managed({ status: 'ready', versions: [{ id: 'v2' } as never, { id: 'v1' } as never], selectedIndex: 1, selectedContent: '<p>old</p>' }),
    }));
    try {
      const frame = container.querySelector('iframe');
      expect(frame?.getAttribute('sandbox')).toBe('');
      expect(frame?.getAttribute('srcdoc')).toContain('old');
    } finally {
      view.unmount();
    }
  });

  it('renders a diff view when viewing a historical diff', () => {
    const view = render(baseProps({
      isHistorical: true,
      historicalViewMode: 'diff',
      historicalDiff: [{ type: 'added', content: 'new line' }],
      managed: managed({ status: 'ready', versions: [{ id: 'v2' } as never, { id: 'v1' } as never], selectedIndex: 1 }),
    }));
    try {
      expect(container.textContent).toContain('new line');
      expect(container.querySelector('iframe')).toBeNull();
    } finally {
      view.unmount();
    }
  });

  it('shows the error message and no iframe when the preview is unavailable', () => {
    const view = render(baseProps({ status: 'error', errorMessage: 'The preview could not be loaded.' }));
    try {
      expect(container.querySelector('iframe')).toBeNull();
      expect(container.textContent).toContain('The preview could not be loaded.');
    } finally {
      view.unmount();
    }
  });

  it('shows a retry affordance when the selected historical version failed to load', () => {
    const retry = vi.fn();
    const failedManaged = managed({ status: 'error', versions: [{ id: 'v1' } as never], errorMessage: 'network error', selectedIndex: 0 });
    failedManaged.retry = retry;
    const view = render(baseProps({ managed: failedManaged, hasVersionHistory: true }));
    try {
      const button = container.querySelector('.artifact-review-retry') as HTMLButtonElement | null;
      expect(button).not.toBeNull();
      act(() => button?.click());
      expect(retry).toHaveBeenCalledTimes(1);
    } finally {
      view.unmount();
    }
  });
});
