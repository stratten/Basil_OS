// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const transportMocks = vi.hoisted(() => ({
  startSession: vi.fn(),
  stopSession: vi.fn(),
  getSession: vi.fn(),
}));

vi.mock('../transport/localWebPreviewTransport', () => ({
  createLocalWebPreviewTransport: () => transportMocks,
}));

const managedHistoryMocks = vi.hoisted(() => ({
  listManagedFileVersions: vi.fn(),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

vi.mock('../managedHistory/managedHistoryApi', () => managedHistoryMocks);

import { useLiveHtmlPreview, type UseLiveHtmlPreviewParams, type UseLiveHtmlPreviewResult } from './useLiveHtmlPreview';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

let container: HTMLDivElement;
let latest: UseLiveHtmlPreviewResult | undefined;
let renderCount = 0;

function TestHarness(props: UseLiveHtmlPreviewParams) {
  renderCount += 1;
  latest = useLiveHtmlPreview(props);
  return null;
}

// Using react-dom directly (no @testing-library) matches this repo's existing
// hook/component test conventions (see useManagedVersionHistory.test.ts).
async function renderHook(params: UseLiveHtmlPreviewParams) {
  const React = await import('react');
  const root = createRoot(container);
  const rerender = (nextParams: UseLiveHtmlPreviewParams) => {
    act(() => { root.render(React.createElement(TestHarness, nextParams)); });
  };
  act(() => { root.render(React.createElement(TestHarness, params)); });
  return { rerender, unmount: () => act(() => root.unmount()) };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function baseParams(overrides: Partial<UseLiveHtmlPreviewParams> = {}): UseLiveHtmlPreviewParams {
  return {
    mode: 'static',
    targetUrl: 'basil-inline-preview://local/tmp/report.html',
    agentTaskId: 'task-1',
    artifactId: 'artifact-1',
    subscribeToArtifactEvents: () => () => undefined,
    getApiBaseUrl: () => '',
    ...overrides,
  };
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  vi.clearAllMocks();
  managedHistoryMocks.listManagedFileVersions.mockResolvedValue([]);
});

afterEach(() => {
  container.remove();
  latest = undefined;
});

describe('useLiveHtmlPreview', () => {
  it('starts connecting in static mode and exposes the target as the rendered URL', async () => {
    const view = await renderHook(baseParams());
    await flush();
    try {
      expect(latest?.status).toBe('connecting');
      expect(latest?.needsLocalServer).toBe(false);
      expect(latest?.renderedPreviewUrl).toContain('basil-inline-preview://local/tmp/report.html');
    } finally {
      view.unmount();
    }
  });

  it('marks devServer mode without a session as needing a local server', async () => {
    const view = await renderHook(baseParams({ mode: 'devServer', targetUrl: '' }));
    await flush();
    try {
      expect(latest?.needsLocalServer).toBe(true);
      expect(latest?.status).toBe('unsupported');
    } finally {
      view.unmount();
    }
  });

  it('starts a dev server and switches to the running session URL', async () => {
    const runningSession = {
      sessionId: 'session-1',
      status: 'running' as const,
      url: 'http://127.0.0.1:4173/',
      host: '127.0.0.1',
      port: 4173,
      pid: 123,
      lastError: null,
      command: 'npm',
      args: ['run', 'dev'],
      cwd: '/tmp/project',
      createdAt: 0,
      stoppedAt: null,
    };
    transportMocks.startSession.mockResolvedValue(runningSession);
    // The session-polling effect fires as soon as `effective.sessionId`
    // becomes defined (immediately after a successful start), so it needs a
    // resolved value too or its own error path would stomp the just-started
    // session back to undefined.
    transportMocks.getSession.mockResolvedValue(runningSession);
    const view = await renderHook(baseParams({ mode: 'devServer', targetUrl: '' }));
    await flush();
    act(() => {
      latest?.serverForm.setCommand('npm');
      latest?.serverForm.setArgs('run dev');
      latest?.serverForm.setCwd('/tmp/project');
    });
    await act(async () => {
      latest?.startServer();
      await new Promise(resolve => setTimeout(resolve, 0));
      await new Promise(resolve => setTimeout(resolve, 0));
    });
    try {
      expect(transportMocks.startSession).toHaveBeenCalledWith(expect.objectContaining({
        agentTaskId: 'task-1',
        artifactId: 'artifact-1',
        command: 'npm',
        args: ['run', 'dev'],
        cwd: '/tmp/project',
      }));
      expect(latest?.needsLocalServer).toBe(false);
      expect(latest?.session?.sessionId).toBe('session-1');
      expect(latest?.targetUrl).toBe('http://127.0.0.1:4173/');
    } finally {
      view.unmount();
    }
  });

  it('bumps the cache-busting revision on refresh so the rendered URL changes', async () => {
    const view = await renderHook(baseParams());
    await flush();
    const before = latest?.renderedPreviewUrl;
    act(() => {
      latest?.refresh();
    });
    try {
      expect(latest?.renderedPreviewUrl).not.toBe(before);
      expect(latest?.statusText).toBe('Preview updated');
    } finally {
      view.unmount();
    }
  });

  it('invokes the injected subscription and refreshes the preview on artifact events', async () => {
    let emit: () => void = () => undefined;
    const subscribeToArtifactEvents = (onEvent: () => void) => {
      emit = onEvent;
      return () => undefined;
    };
    const view = await renderHook(baseParams({ subscribeToArtifactEvents }));
    await flush();
    const before = latest?.renderedPreviewUrl;
    act(() => {
      emit();
    });
    try {
      expect(latest?.renderedPreviewUrl).not.toBe(before);
    } finally {
      view.unmount();
    }
  });

  it('does not issue its own version-history fetch when an external history result is supplied', async () => {
    const externalManagedHistory = {
      state: { status: 'ready' as const, versions: [], selectedIndex: 0, restoreStatus: 'idle' as const },
      canRestore: false,
      selectVersion: vi.fn(),
      restore: vi.fn(),
      retry: vi.fn(),
    };
    const view = await renderHook(baseParams({ canonicalPath: '/tmp/report.html', externalManagedHistory }));
    await flush();
    try {
      expect(managedHistoryMocks.listManagedFileVersions).not.toHaveBeenCalled();
      expect(latest?.managed).toBe(externalManagedHistory);
    } finally {
      view.unmount();
    }
  });

  it('stops the dev-server session on unmount only when stopServerOnUnmount is set', async () => {
    transportMocks.stopSession.mockResolvedValue({
      sessionId: 'session-1',
      status: 'stopped',
      url: '',
      host: '',
      port: 0,
      pid: null,
      lastError: null,
      command: '',
      args: [],
      cwd: '',
      createdAt: 0,
      stoppedAt: 1,
    });
    transportMocks.getSession.mockResolvedValue({
      sessionId: 'session-1',
      status: 'running',
      url: 'http://127.0.0.1:4173/',
      host: '127.0.0.1',
      port: 4173,
      pid: 1,
      lastError: null,
      command: 'npm',
      args: [],
      cwd: '/tmp',
      createdAt: 0,
      stoppedAt: null,
    });
    const view = await renderHook(baseParams({
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173/',
      sessionId: 'session-1',
      stopServerOnUnmount: true,
    }));
    await flush();
    await act(async () => {
      view.unmount();
      await Promise.resolve();
    });
    expect(transportMocks.stopSession).toHaveBeenCalledWith({
      agentTaskId: 'task-1',
      artifactId: 'artifact-1',
      sessionId: 'session-1',
    });
  });

  it('leaves a running dev-server session alone on unmount by default', async () => {
    transportMocks.getSession.mockResolvedValue({
      sessionId: 'session-1',
      status: 'running',
      url: 'http://127.0.0.1:4173/',
      host: '127.0.0.1',
      port: 4173,
      pid: 1,
      lastError: null,
      command: 'npm',
      args: [],
      cwd: '/tmp',
      createdAt: 0,
      stoppedAt: null,
    });
    const view = await renderHook(baseParams({
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173/',
      sessionId: 'session-1',
    }));
    await flush();
    await act(async () => {
      view.unmount();
      await Promise.resolve();
    });
    await flush();
    expect(transportMocks.stopSession).not.toHaveBeenCalled();
  });
});
