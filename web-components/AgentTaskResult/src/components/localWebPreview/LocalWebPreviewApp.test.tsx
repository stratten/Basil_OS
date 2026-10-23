// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LocalWebPreviewApp from './LocalWebPreviewApp';
import * as bridge from './localWebPreviewBridge';
import type { LocalWebPreviewInitMessage } from './localWebPreviewBridge';
import * as api from '../../services/api';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

class TestResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}

let originalResizeObserver: typeof ResizeObserver;

const bridgeMocks = vi.hoisted(() => ({
  init: {
    mode: 'static' as 'static' | 'devServer',
    targetUrl: 'file:///tmp/demo.html',
    artifactId: 'artifact-1',
    agentTaskId: 'task-1',
    displayName: 'demo.html',
    port: 8000,
  } as LocalWebPreviewInitMessage,
  validationFeedbackHandler: undefined as ((payload: { text: string }) => void) | undefined,
  validationServerHandler: undefined as ((payload: {
    command: string;
    args: string[];
    cwd: string;
    port: number;
  }) => void) | undefined,
}));

const websocketMocks = vi.hoisted(() => ({
  instances: [] as Array<{
    eventHandler?: (event: Record<string, unknown>) => void;
    connectHandler?: () => void;
    connect: ReturnType<typeof vi.fn>;
    disconnect: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock('./localWebPreviewBridge', () => ({
  registerLocalWebPreviewInitHandler: vi.fn((callback) => {
    callback(bridgeMocks.init);
    return () => undefined;
  }),
  registerConsoleEvidenceHandler: vi.fn(() => () => undefined),
  registerLocalWebPreviewValidationFeedbackHandler: vi.fn((callback) => {
    bridgeMocks.validationFeedbackHandler = callback;
    return () => {
      if (bridgeMocks.validationFeedbackHandler === callback) {
        bridgeMocks.validationFeedbackHandler = undefined;
      }
    };
  }),
  registerLocalWebPreviewValidationServerHandler: vi.fn((callback) => {
    bridgeMocks.validationServerHandler = callback;
    return () => {
      if (bridgeMocks.validationServerHandler === callback) {
        bridgeMocks.validationServerHandler = undefined;
      }
    };
  }),
  closeLocalWebPreviewWindow: vi.fn(),
  minimizeLocalWebPreviewWindow: vi.fn(),
  openExternalUrl: vi.fn(),
  captureScreenshot: vi.fn().mockResolvedValue({ path: '/tmp/current-preview.png' }),
  requestConsoleEvidence: vi.fn().mockResolvedValue(''),
  reportLocalWebPreviewChromeHeight: vi.fn(),
  notifyLocalPreviewServerSessionStarted: vi.fn(),
  notifyLocalPreviewServerSessionDenied: vi.fn(),
  notifyLocalWebPreviewWindowWillClose: vi.fn(),
  readCurrentPreviewUrl: vi.fn((_frame: HTMLIFrameElement | null, fallbackUrl: string) => ({
    url: fallbackUrl,
    status: 'fallback' as const,
  })),
}));

vi.mock('../../services/api', () => ({
  setBaseUrl: vi.fn(),
  processAgentTask: vi.fn().mockResolvedValue({}),
}));

const managedHistoryMocks = vi.hoisted(() => ({
  listManagedFileVersions: vi.fn().mockResolvedValue([]),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

vi.mock('../artifacts/managedHistory/managedHistoryApi', () => managedHistoryMocks);

vi.mock('../../services/websocket', () => ({
  WebSocketManager: class {
    eventHandler?: (event: Record<string, unknown>) => void;
    connectHandler?: () => void;
    connect = vi.fn();
    disconnect = vi.fn();
    constructor() {
      websocketMocks.instances.push(this);
    }
    subscribe(handler: (event: Record<string, unknown>) => void) {
      this.eventHandler = handler;
      return () => {
        this.eventHandler = undefined;
      };
    }
    onConnect(handler: () => void) {
      this.connectHandler = handler;
      return () => {
        this.connectHandler = undefined;
      };
    }
  },
}));

let container: HTMLDivElement;

beforeEach(() => {
  originalResizeObserver = globalThis.ResizeObserver;
  globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
  container = document.createElement('div');
  document.body.appendChild(container);
  bridgeMocks.init = {
    mode: 'static',
    targetUrl: 'file:///tmp/demo.html',
    artifactId: 'artifact-1',
    agentTaskId: 'task-1',
    displayName: 'demo.html',
    port: 8000,
  };
  websocketMocks.instances.length = 0;
  bridgeMocks.validationFeedbackHandler = undefined;
  bridgeMocks.validationServerHandler = undefined;
  vi.stubGlobal('fetch', vi.fn());
  vi.clearAllMocks();
  managedHistoryMocks.listManagedFileVersions.mockResolvedValue([]);
});

afterEach(() => {
  globalThis.ResizeObserver = originalResizeObserver;
  vi.unstubAllGlobals();
  container.remove();
});

function mount() {
  const root = createRoot(container);
  act(() => {
    root.render(<LocalWebPreviewApp />);
  });
  return {
    root,
    cleanup: () => {
      act(() => {
        root.unmount();
      });
    },
  };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('LocalWebPreviewApp', () => {
  it('renders the ready status for a static preview', async () => {
    const view = mount();
    await flush();

    try {
      await act(async () => {
        container.querySelector('iframe')?.dispatchEvent(new Event('load'));
      });
      expect(container.textContent).toContain('Ready');
      expect(container.querySelector('.basil-webkit-window-frame')).not.toBeNull();
      expect(container.querySelector('.file-preview-window-header')).not.toBeNull();
      expect(container.textContent).toContain('Rendered preview');
      expect(container.querySelector('[aria-label="Refresh preview"]')).not.toBeNull();
      expect(container.querySelector('[aria-label="Refresh preview"] span[style*="mask-image"]')).not.toBeNull();
      expect(container.querySelector('[aria-label="Open in default browser"] span[style*="mask-image"]')).not.toBeNull();
      expect(container.querySelector('iframe')?.getAttribute('src')).toBe('file:///tmp/demo.html?basilPreviewRevision=0');
    } finally {
      view.cleanup();
    }
  });

  it('posts openExternalUrl when its icon control is clicked', async () => {
    const view = mount();
    await flush();

    try {
      act(() => {
        Array.from(container.querySelectorAll('button'))
          .find(button => button.getAttribute('aria-label') === 'Open in default browser')
          ?.click();
      });
      expect(bridge.openExternalUrl).toHaveBeenCalledWith('file:///tmp/demo.html');
    } finally {
      view.cleanup();
    }
  });

  it('keeps feedback screenshot-free while retaining its character limit', async () => {
    const view = mount();
    await flush();

    try {
      expect(container.querySelector('[aria-label="Take screenshot"]')).toBeNull();
      expect(container.querySelector('img[alt="Preview screenshot"]')).toBeNull();
      expect((container.querySelector('textarea') as HTMLTextAreaElement).maxLength).toBe(4000);
    } finally {
      view.cleanup();
    }
  });

  it('refreshes a matched artifact event with a cache-busting preview revision', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://fixture/report.html',
      wsUrl: 'ws://localhost:8000/ws',
    };
    const view = mount();
    await flush();

    try {
      const manager = websocketMocks.instances[websocketMocks.instances.length - 1]!;
      expect(manager.connect).toHaveBeenCalledWith('ws://localhost:8000/ws');
      expect(container.querySelector('iframe')?.getAttribute('src')).toContain('basilPreviewRevision=0');
      await act(async () => {
        manager.eventHandler?.({
          event_type: 'agent_task_artifact',
          agent_task_id: 'task-1',
          agent_task_artifact: { artifact_id: 'artifact-1' },
        });
      });
      expect(container.querySelector('iframe')?.getAttribute('src')).toContain('basilPreviewRevision=1');
      expect(container.textContent).toContain('Preview updated');
    } finally {
      view.cleanup();
    }
  });

  it('accepts a matched root task artifact event', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://fixture/report.html',
      wsUrl: 'ws://localhost:8000/ws',
    };
    const view = mount();
    await flush();

    try {
      const manager = websocketMocks.instances[websocketMocks.instances.length - 1]!;
      await act(async () => {
        manager.eventHandler?.({
          event_type: 'agent_task_artifact',
          agent_task_id: 'follow-up-task',
          root_task_id: 'task-1',
          agent_task_artifact: { artifact_id: 'artifact-1' },
        });
      });
      expect(container.querySelector('iframe')?.getAttribute('src')).toContain('basilPreviewRevision=1');
    } finally {
      view.cleanup();
    }
  });

  it('ignores unrelated artifact events', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://fixture/report.html',
      wsUrl: 'ws://localhost:8000/ws',
    };
    const view = mount();
    await flush();

    try {
      const manager = websocketMocks.instances[websocketMocks.instances.length - 1]!;
      await act(async () => {
        manager.eventHandler?.({
          event_type: 'agent_task_artifact',
          agent_task_id: 'other-task',
          root_task_id: 'other-root-task',
          agent_task_artifact: { artifact_id: 'artifact-1' },
        });
        manager.eventHandler?.({
          event_type: 'agent_task_artifact',
          agent_task_id: 'task-1',
          agent_task_artifact: { artifact_id: 'other-artifact' },
        });
        manager.eventHandler?.({ event_type: 'agent_task_progress' });
      });
      expect(container.querySelector('iframe')?.getAttribute('src')).toContain('basilPreviewRevision=0');
    } finally {
      view.cleanup();
    }
  });

  it('refreshes once after reconnect without static preview polling', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://fixture/report.html',
      wsUrl: 'ws://localhost:8000/ws',
    };
    const intervalSpy = vi.spyOn(globalThis, 'setInterval');
    const view = mount();
    await flush();

    try {
      const manager = websocketMocks.instances[websocketMocks.instances.length - 1]!;
      await act(async () => {
        manager.connectHandler?.();
        manager.connectHandler?.();
      });
      expect(container.querySelector('iframe')?.getAttribute('src')).toContain('basilPreviewRevision=1');
      expect(intervalSpy).not.toHaveBeenCalled();
    } finally {
      intervalSpy.mockRestore();
      view.cleanup();
    }
  });

  it('disables Send as follow-up when feedback is empty', async () => {
    const view = mount();
    await flush();

    try {
      const submitButton = Array.from(container.querySelectorAll('button'))
        .find(button => button.textContent?.includes('Send follow-up')) as HTMLButtonElement | undefined;
      expect(submitButton?.disabled).toBe(true);
    } finally {
      view.cleanup();
    }
  });

  it('submits validation feedback through the production feedback handler', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://preview/demo.html',
    };
    const view = mount();
    await flush();

    try {
      await act(async () => {
        bridgeMocks.validationFeedbackHandler?.({ text: 'Capture the current preview state.' });
        await Promise.resolve();
      });
      await vi.waitFor(() => {
        expect(api.processAgentTask).toHaveBeenCalledOnce();
      });
      expect(api.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
        agent_task: 'Local web preview feedback on basil-preview-file://preview/demo.html:\n\nCapture the current preview state.',
        root_task_id: 'task-1',
        previous_task_id: 'task-1',
      }));
      expect(bridge.captureScreenshot).toHaveBeenCalledOnce();
    } finally {
      view.cleanup();
    }
  });

  it('rejects a malformed validation server request before transport', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'file:///tmp/local-preview/index.html',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'index.html',
      port: 8000,
    };
    const view = mount();
    await flush();

    try {
      await act(async () => {
        bridgeMocks.validationServerHandler?.({
          command: 'node',
          args: ['server.py'],
          cwd: '/tmp/local-preview',
          port: 43123,
        });
      });
      expect(fetch).not.toHaveBeenCalled();
      expect(container.querySelector('[role="alert"]')?.textContent).toContain('Enter a command');
    } finally {
      view.cleanup();
    }
  });

  it('starts the expected validation server through the production server handler', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'file:///tmp/local-preview/index.html',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'index.html',
      port: 8000,
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'validation-session',
        status: 'running',
        url: 'http://127.0.0.1:43123',
        host: '127.0.0.1',
        port: 43123,
        pid: 42,
        last_error: null,
        command: 'python3',
        args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
        cwd: '/tmp/local-preview',
        created_at: 1700000000,
        stopped_at: null,
      }),
    } as Response);
    const view = mount();
    await flush();

    try {
      await act(async () => {
        bridgeMocks.validationServerHandler?.({
          command: 'python3',
          args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
          cwd: '/tmp/local-preview',
          port: 43123,
        });
        await Promise.resolve();
      });
      await vi.waitFor(() => {
        expect(fetchMock).toHaveBeenCalledWith(
          'http://localhost:8000/api/v1/agent-tasks/task-2/artifacts/artifact-2/local-preview/sessions',
          expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({
              command: 'python3',
              args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
              cwd: '/tmp/local-preview',
              port: 43123,
            }),
          }),
        );
      });
      expect(bridge.notifyLocalPreviewServerSessionStarted).toHaveBeenCalledWith('validation-session');
    } finally {
      view.cleanup();
    }
  });

  it('notifies the native host when the server-preview session is denied', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'file:///tmp/local-preview/index.html',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'index.html',
      port: 8000,
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'denied-session',
        status: 'denied',
        url: null,
        host: '127.0.0.1',
        port: 43123,
        pid: null,
        last_error: 'Denied by validation policy',
        command: 'python3',
        args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
        cwd: '/tmp/local-preview',
        created_at: 1700000000,
        stopped_at: null,
      }),
    } as Response);
    const view = mount();
    await flush();

    try {
      await act(async () => {
        bridgeMocks.validationServerHandler?.({
          command: 'python3',
          args: ['server.py', '--host', '127.0.0.1', '--port', '43123'],
          cwd: '/tmp/local-preview',
          port: 43123,
        });
        await Promise.resolve();
      });
      await vi.waitFor(() => {
        expect(bridge.notifyLocalPreviewServerSessionDenied).toHaveBeenCalledWith(
          'denied-session',
          'Denied by validation policy',
        );
      });
      expect(bridge.notifyLocalPreviewServerSessionStarted).not.toHaveBeenCalled();
      expect(container.textContent).toContain('Unsupported');
    } finally {
      view.cleanup();
    }
  });

  it('starts an approval-gated local server before rendering a non-html artifact', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'file:///tmp/project',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'project',
      port: 8000,
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-2',
        status: 'running',
        url: 'http://127.0.0.1:4173',
        host: '127.0.0.1',
        port: 4173,
        pid: 42,
        last_error: null,
        command: 'npm',
        args: ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '4173'],
        cwd: '/tmp',
        created_at: 1700000000,
        stopped_at: null,
      }),
    } as Response);
    const view = mount();
    await flush();

    try {
      const inputs = Array.from(container.querySelectorAll('input')) as HTMLInputElement[];
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
        setter?.call(inputs[0], 'npm');
        inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
        setter?.call(inputs[1], 'run dev -- --host 127.0.0.1 --port 4173');
        inputs[1].dispatchEvent(new Event('input', { bubbles: true }));
      });
      const startServerButton = Array.from(container.querySelectorAll('button'))
        .find(button => button.textContent?.includes('Preview with a local server'));
      // The 'play' icon renders as an inline outline <svg> (not a masked <span>)
      // to match the app's thin-stroke icon language.
      expect(startServerButton?.querySelector('svg')).not.toBeNull();
      await act(async () => {
        startServerButton?.click();
        await Promise.resolve();
      });
      await flush();

      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agent-tasks/task-2/artifacts/artifact-2/local-preview/sessions',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            command: 'npm',
            args: ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '4173'],
            cwd: '/tmp',
            port: 4173,
          }),
        }),
      );
      await vi.waitFor(() => {
        expect(container.querySelector('iframe')?.getAttribute('src')).toBe('http://127.0.0.1:4173/?basilPreviewRevision=0');
      });
      expect(container.textContent).toContain('Command');
      expect(container.textContent).toContain('npm run dev -- --host 127.0.0.1 --port 4173');
      expect(container.textContent).toContain('Working directory');
      expect(container.textContent).toContain('/tmp');
      expect(container.textContent).toContain('127.0.0.1:4173');
      expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Stop preview')).toBe(true);
    } finally {
      view.cleanup();
    }
  });

  it('does not allow feedback before a local-server session starts', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'file:///tmp/project',
      artifactId: 'artifact-2',
      agentTaskId: 'task-2',
      displayName: 'project',
      port: 8000,
    };
    const view = mount();
    await flush();

    try {
      const input = container.querySelector('textarea') as HTMLTextAreaElement;
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        setter?.call(input, 'Review this server preview.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const submitButton = Array.from(container.querySelectorAll('button'))
        .find(button => button.textContent?.includes('Send follow-up')) as HTMLButtonElement | undefined;
      expect(submitButton?.disabled).toBe(true);
    } finally {
      view.cleanup();
    }
  });

  it('uses the authorized static preview URL when feedback is submitted', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://preview/demo.html',
    };
    const view = mount();
    await flush();

    try {
      const input = container.querySelector('textarea') as HTMLTextAreaElement;
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        setter?.call(input, 'Fix the header spacing.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const submitButton = Array.from(container.querySelectorAll('button'))
        .find(button => button.textContent?.includes('Send follow-up')) as HTMLButtonElement | undefined;
      expect(submitButton?.querySelector('span[style*="mask-image"]')).not.toBeNull();
      expect(submitButton?.disabled).toBe(false);
      await act(async () => {
        submitButton?.click();
        await new Promise(resolve => window.setTimeout(resolve, 100));
      });
      expect(api.processAgentTask).toHaveBeenCalledWith({
        agent_task: 'Local web preview feedback on basil-preview-file://preview/demo.html:\n\nFix the header spacing.',
        agent_task_id: expect.any(String),
        root_task_id: 'task-1',
        previous_task_id: 'task-1',
        reference_paths: ['/tmp/current-preview.png'],
        local_preview_feedback: {
          source_artifact_id: 'artifact-1',
          mode: 'static',
          preview_url: 'basil-preview-file://preview/demo.html',
          location_status: 'fallback',
          screenshot_path: '/tmp/current-preview.png',
          console_evidence: '',
          session_id: undefined,
          session_status: undefined,
        },
      });
      expect(vi.mocked(api.processAgentTask).mock.calls[0]?.[0]?.local_preview_feedback).not.toHaveProperty('network_evidence');
      expect(vi.mocked(api.processAgentTask).mock.calls[0]?.[0]?.reference_paths).toEqual(['/tmp/current-preview.png']);
      expect(bridge.captureScreenshot).toHaveBeenCalledOnce();
      expect(bridge.readCurrentPreviewUrl).not.toHaveBeenCalled();
    } finally {
      view.cleanup();
    }
  });

  it('submits feedback without a reference when automatic capture is unavailable', async () => {
    vi.mocked(bridge.captureScreenshot).mockResolvedValueOnce({ error: 'Snapshot unavailable' });
    bridgeMocks.init = {
      ...bridgeMocks.init,
      previewContentUrl: 'basil-preview-file://preview/demo.html',
    };
    const view = mount();
    await flush();

    try {
      const input = container.querySelector('textarea') as HTMLTextAreaElement;
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        setter?.call(input, 'Use the current layout.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await act(async () => {
        Array.from(container.querySelectorAll('button'))
          .find(button => button.textContent?.includes('Send follow-up'))
          ?.click();
        await new Promise(resolve => window.setTimeout(resolve, 100));
      });
      expect(api.processAgentTask).toHaveBeenCalledWith({
        agent_task: 'Local web preview feedback on basil-preview-file://preview/demo.html:\n\nUse the current layout.',
        agent_task_id: expect.any(String),
        root_task_id: 'task-1',
        previous_task_id: 'task-1',
        local_preview_feedback: {
          source_artifact_id: 'artifact-1',
          mode: 'static',
          preview_url: 'basil-preview-file://preview/demo.html',
          location_status: 'fallback',
          screenshot_path: undefined,
          console_evidence: '',
          session_id: undefined,
          session_status: undefined,
        },
      });
      expect(container.querySelector('[role="alert"]')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('stops an active dev-server session when the preview closes', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173',
      artifactId: 'artifact-3',
      agentTaskId: 'task-3',
      displayName: 'project',
      sessionId: 'session-3',
      port: 8000,
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-3',
        status: 'running',
        url: 'http://127.0.0.1:4173',
        host: '127.0.0.1',
        port: 4173,
        pid: 44,
        last_error: null,
        command: 'python3',
        args: ['-m', 'http.server', '4173'],
        cwd: '/tmp/project',
        created_at: 1700000000,
        stopped_at: null,
      }),
    } as Response);
    const view = mount();
    await flush();
    view.cleanup();

    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agent-tasks/task-3/artifacts/artifact-3/local-preview/sessions/session-3/stop',
        expect.objectContaining({ method: 'POST' }),
      );
    });
    expect(bridge.notifyLocalWebPreviewWindowWillClose).toHaveBeenCalled();
  });

  it('clears stale lifecycle controls when a persisted dev-server session is unavailable', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173',
      artifactId: 'artifact-3',
      agentTaskId: 'task-3',
      displayName: 'project',
      sessionId: 'session-3',
      port: 8000,
    };
    vi.mocked(fetch).mockResolvedValue({ ok: false, status: 404 } as Response);
    const view = mount();
    await flush();

    try {
      await vi.waitFor(() => {
        expect(container.querySelector('[role="alert"]')?.textContent).toContain(
          'Local web preview request failed with status 404',
        );
      });
      expect(container.textContent).not.toContain('Working directory');
      expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Stop preview')).toBe(false);
    } finally {
      view.cleanup();
    }
  });

  it('stops a running session from the visible Stop preview action', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173',
      artifactId: 'artifact-3',
      agentTaskId: 'task-3',
      displayName: 'project',
      sessionId: 'session-3',
      port: 8000,
    };
    const fetchMock = vi.mocked(fetch);
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      const stopped = url.endsWith('/stop');
      return {
        ok: true,
        json: async () => ({
          session_id: 'session-3',
          status: stopped ? 'stopped' : 'running',
          url: 'http://127.0.0.1:4173',
          host: '127.0.0.1',
          port: 4173,
          pid: stopped ? null : 44,
          last_error: null,
          command: 'python3',
          args: ['-m', 'http.server', '4173'],
          cwd: '/tmp/project',
          created_at: 1700000000,
          stopped_at: stopped ? 1700000005 : null,
        }),
      } as Response;
    });
    const view = mount();
    await flush();

    try {
      await vi.waitFor(() => {
        expect(container.textContent).toContain('python3 -m http.server 4173');
      });
      await act(async () => {
        Array.from(container.querySelectorAll('button'))
          .find(button => button.textContent === 'Stop preview')
          ?.click();
        await Promise.resolve();
      });
      await flush();
      expect(fetchMock).toHaveBeenCalledWith(
        'http://localhost:8000/api/v1/agent-tasks/task-3/artifacts/artifact-3/local-preview/sessions/session-3/stop',
        expect.objectContaining({ method: 'POST' }),
      );
      expect(container.textContent).toContain('Server stopped');
      expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Stop preview')).toBe(false);
    } finally {
      view.cleanup();
    }
  });

  it('submits the current loopback iframe URL when the frame location is readable', async () => {
    bridgeMocks.init = {
      mode: 'devServer',
      targetUrl: 'http://127.0.0.1:4173',
      artifactId: 'artifact-4',
      agentTaskId: 'task-4',
      displayName: 'dashboard',
      sessionId: 'session-4',
      port: 8000,
    };
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        session_id: 'session-4',
        status: 'running',
        url: 'http://127.0.0.1:4173',
        host: '127.0.0.1',
        port: 4173,
        pid: 45,
        last_error: null,
        command: 'python3',
        args: ['-m', 'http.server', '4173'],
        cwd: '/tmp/project',
        created_at: 1700000000,
        stopped_at: null,
      }),
    } as Response);
    vi.mocked(bridge.readCurrentPreviewUrl).mockReturnValueOnce({
      url: 'http://127.0.0.1:4173/dashboard',
      status: 'current',
    });
    const view = mount();
    await flush();

    try {
      expect(Array.from(container.querySelectorAll('button')).some(button => button.textContent === 'Stop preview')).toBe(true);
      const input = container.querySelector('textarea') as HTMLTextAreaElement;
      await act(async () => {
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
        setter?.call(input, 'Move the header.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await act(async () => {
        Array.from(container.querySelectorAll('button'))
          .find(button => button.textContent?.includes('Send follow-up'))
          ?.click();
        await new Promise(resolve => window.setTimeout(resolve, 100));
      });
      expect(api.processAgentTask).toHaveBeenCalledWith(expect.objectContaining({
        agent_task: 'Local web preview feedback on http://127.0.0.1:4173/dashboard:\n\nMove the header.',
        local_preview_feedback: expect.objectContaining({
          preview_url: 'http://127.0.0.1:4173/dashboard',
          location_status: 'current',
        }),
      }));
      expect(vi.mocked(api.processAgentTask).mock.calls[0]?.[0].local_preview_feedback).not.toHaveProperty('network_evidence');
    } finally {
      view.cleanup();
    }
  });
});

function managedVersion(id: string, agentTaskId: string) {
  return {
    id,
    rootTaskId: 'root-1',
    agentTaskId,
    canonicalPath: '/tmp/demo.html',
    operation: 'overwrite' as const,
    origin: 'model' as const,
    postImageSizeBytes: 10,
    restoresChangeId: null,
    createdAt: '2026-01-01T00:00:00Z',
    appliedAt: '2026-01-01T00:00:00Z',
  };
}

describe('LocalWebPreviewApp managed version parity', () => {
  it('renders no version controls when init has no canonicalPath', async () => {
    const view = mount();
    await flush();

    try {
      expect(container.querySelector('.artifact-review-version-select')).toBeNull();
      expect(managedHistoryMocks.listManagedFileVersions).not.toHaveBeenCalled();
    } finally {
      view.cleanup();
    }
  });

  it('renders a sandboxed srcDoc with a historical-view caption when a non-head version is selected', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      canonicalPath: '/tmp/demo.html',
      rootTaskId: 'root-1',
    };
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-1'),
      managedVersion('change-1', 'task-0'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/tmp/demo.html', content: `<p>${id}</p>`, truncated: false, byteSize: 8 }));

    const view = mount();
    await flush();
    await flush();

    try {
      const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement | null;
      expect(select).not.toBeNull();
      act(() => { select!.click(); });
      const option = document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option')[1];
      act(() => { option.click(); });
      await flush();
      expect(container.textContent).toContain('Viewing an earlier version');
      const historicalFrame = container.querySelector('iframe[sandbox=""]');
      expect(historicalFrame).not.toBeNull();
      expect(historicalFrame?.getAttribute('srcdoc')).toContain('change-1');
    } finally {
      view.cleanup();
    }
  });

  it('disables Send follow-up while viewing a historical version', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      canonicalPath: '/tmp/demo.html',
      rootTaskId: 'root-1',
    };
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-1'),
      managedVersion('change-1', 'task-0'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/tmp/demo.html', content: `<p>${id}</p>`, truncated: false, byteSize: 8 }));

    const view = mount();
    await flush();
    await flush();

    try {
      const input = container.querySelector('textarea') as HTMLTextAreaElement;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set;
      await act(async () => {
        setter?.call(input, 'Move the header.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const sendButton = () => Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes('Send follow-up')) as HTMLButtonElement;
      expect(sendButton().disabled).toBe(false);

      const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement | null;
      act(() => { select!.click(); });
      const option = document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option')[1];
      act(() => { option.click(); });
      await flush();
      expect(sendButton().disabled).toBe(true);
    } finally {
      view.cleanup();
    }
  });

  it('does not render the previously selected HTML while an older version is loading', async () => {
    let loadOlderVersion: ((value: { changeId: string; canonicalPath: string; content: string; truncated: boolean; byteSize: number }) => void) | undefined;
    bridgeMocks.init = {
      ...bridgeMocks.init,
      canonicalPath: '/tmp/demo.html',
    };
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-1'),
      managedVersion('change-1', 'task-0'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => {
      if (id === 'change-2') {
        return Promise.resolve({ changeId: id, canonicalPath: '/tmp/demo.html', content: '<p>current</p>', truncated: false, byteSize: 14 });
      }
      if (loadOlderVersion) {
        return new Promise(resolve => { loadOlderVersion = resolve; });
      }
      return Promise.resolve({ changeId: id, canonicalPath: '/tmp/demo.html', content: '<p>older</p>', truncated: false, byteSize: 12 });
    });

    const view = mount();
    await flush();
    await flush();

    try {
      const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
      loadOlderVersion = () => undefined;
      act(() => { select.click(); });
      const option = document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option')[1];
      act(() => { option.click(); });
      await flush();
      expect(container.textContent).toContain('Loading selected version...');
      expect(container.querySelector('iframe[sandbox=""]')).toBeNull();
    } finally {
      loadOlderVersion?.({ changeId: 'change-1', canonicalPath: '/tmp/demo.html', content: '<p>older</p>', truncated: false, byteSize: 12 });
      view.cleanup();
    }
  });

  it('refreshes the version list when a matching artifact websocket event refreshes the live preview', async () => {
    bridgeMocks.init = {
      ...bridgeMocks.init,
      canonicalPath: '/tmp/demo.html',
      wsUrl: 'ws://localhost:8000/ws',
    };
    managedHistoryMocks.listManagedFileVersions
      .mockResolvedValueOnce([managedVersion('change-1', 'task-1')])
      .mockResolvedValueOnce([managedVersion('change-2', 'task-1'), managedVersion('change-1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/tmp/demo.html', content: `<p>${id}</p>`, truncated: false, byteSize: 8 }));

    const view = mount();
    await flush();
    await flush();

    try {
      const manager = websocketMocks.instances[websocketMocks.instances.length - 1]!;
      await act(async () => {
        manager.eventHandler?.({
          event_type: 'agent_task_artifact',
          agent_task_id: 'task-1',
          agent_task_artifact: { artifact_id: 'artifact-1' },
        });
        await Promise.resolve();
        await Promise.resolve();
        await Promise.resolve();
      });
      expect(managedHistoryMocks.listManagedFileVersions).toHaveBeenCalledTimes(2);
      expect(container.querySelector('.artifact-review-version-select .tokenized-select__label')?.textContent).toBe('Current');
    } finally {
      view.cleanup();
    }
  });
});
