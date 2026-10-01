// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AgentTaskArtifactPresentation } from '../../artifacts/artifactContract';
import type { ArtifactPreviewTransport, FilePreviewPayload } from './transport/artifactPreviewTransport';
import { InlineArtifactPreview } from './InlineArtifactPreview';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

class TestResizeObserver {
  observe() {}
  disconnect() {}
  unobserve() {}
}

let originalRect: typeof HTMLElement.prototype.getBoundingClientRect;
let originalResizeObserver: typeof ResizeObserver;

beforeEach(() => {
  originalRect = HTMLElement.prototype.getBoundingClientRect;
  originalResizeObserver = globalThis.ResizeObserver;
  HTMLElement.prototype.getBoundingClientRect = () => new DOMRect(0, 0, 320, 180);
  globalThis.ResizeObserver = TestResizeObserver as unknown as typeof ResizeObserver;
});

afterEach(() => {
  HTMLElement.prototype.getBoundingClientRect = originalRect;
  globalThis.ResizeObserver = originalResizeObserver;
});

function fakeTransport(): ArtifactPreviewTransport {
  return {
    previewFile: vi.fn(),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn().mockReturnValue(() => {}),
    setInlineNativePreviewFrame: vi.fn(),
    hideInlineNativePreview: vi.fn(),
    clearInlineNativePreview: vi.fn(),
  };
}

function artifact(overrides: Partial<AgentTaskArtifactPresentation> = {}): AgentTaskArtifactPresentation {
  return Object.assign({
    artifactId: 'artifact-report',
    displayName: 'résumé-東京.md',
    localPath: '/private/reports/résumé-東京.md',
    artifactKind: 'file',
    lifecycle: 'ready',
    preview: { capability: 'unknown' },
    verification: { status: 'unknown' },
  }, overrides);
}

function payload(
  kind: FilePreviewPayload['kind'],
  content?: string,
  error?: string,
): FilePreviewPayload {
  const value: FilePreviewPayload = {
    requestId: 'preview-test',
    path: '/private/reports/résumé-東京.md',
    name: 'résumé-東京.md',
    kind,
  };
  if (content !== undefined) value.content = content;
  if (error !== undefined) value.error = error;
  return value;
}

function deferred<T>() {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

function mount(
  initialArtifact?: AgentTaskArtifactPresentation,
  presentation: 'standalone' | 'tray' = 'standalone',
  transport: ArtifactPreviewTransport = fakeTransport(),
  actions: { onOpenFile?: (path: string) => void; onOpenContainingFolder?: (path: string) => void; onOpenPreviewWindow?: (path: string) => void; onOpenLocalWebPreview?: (path: string) => void } = {},
  context: { agentTaskId?: string; rootTaskId?: string } = {},
) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const render = (nextArtifact?: AgentTaskArtifactPresentation) => {
    act(() => {
      root.render(
        <InlineArtifactPreview
          artifact={nextArtifact}
          presentation={presentation}
          transport={transport}
          agentTaskId={context.agentTaskId}
          rootTaskId={context.rootTaskId}
          onOpenFile={actions.onOpenFile}
          onOpenContainingFolder={actions.onOpenContainingFolder}
          onOpenPreviewWindow={actions.onOpenPreviewWindow}
          onOpenLocalWebPreview={actions.onOpenLocalWebPreview}
          subscribeToEvents={() => () => undefined}
        />,
      );
    });
  };
  render(initialArtifact);
  return {
    container,
    transport,
    render,
    cleanup: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

async function flushPreview() {
  await act(async () => {
    await Promise.resolve();
  });
}

describe('InlineArtifactPreview', () => {
  it('renders nothing and sends no bridge request without a selected artifact', () => {
    const view = mount();

    try {
      expect(view.container.innerHTML).toBe('');
      expect(view.transport.previewFile).not.toHaveBeenCalled();
    } finally {
      view.cleanup();
    }
  });

  it.each(['supported', 'unknown'] as const)('requests a %s eligible artifact and renders Markdown safely', async (capability) => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('markdown', '# Overview'));
    const view = mount(artifact({ preview: { capability } }), 'standalone', transport);

    try {
      expect(transport.previewFile).toHaveBeenCalledWith('/private/reports/résumé-東京.md');
      expect(view.container.textContent).toContain('Loading preview');
      expect(view.container.querySelector('.inline-artifact-preview-eyebrow')?.textContent).toBe('File Preview');
      await flushPreview();
      expect(view.container.textContent).toContain('Markdown Preview');
      expect(view.container.textContent).toContain('Overview');
      expect(view.container.querySelector('.inline-artifact-preview-body .result-section')).not.toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('renders tray presentation without a standalone heading or file actions', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('markdown', '# Overview'));
    const view = mount(artifact(), 'tray', transport);

    try {
      expect(view.container.textContent).toContain('Loading preview');
      expect(view.container.querySelector('.inline-artifact-preview-heading')).toBeNull();
      await flushPreview();
      expect(view.container.textContent).toContain('Overview');
      expect(Array.from(view.container.querySelectorAll('button')).map(button => button.textContent)).not.toContain('Open File');
      expect(Array.from(view.container.querySelectorAll('button')).map(button => button.textContent)).not.toContain('Show in Folder');
      expect(Array.from(view.container.querySelectorAll('button')).map(button => button.textContent)).not.toContain('Open Preview Window');
      expect(Array.from(view.container.querySelectorAll('button')).map(button => button.textContent)).not.toContain('Preview in Browser');
    } finally {
      view.cleanup();
    }
  });

  it('renders source payloads as escaped text rather than DOM markup', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('htmlSource', '<draft & safely>'));
    const view = mount(artifact(), 'standalone', transport);

    try {
      await flushPreview();
      expect(view.container.querySelector('.inline-artifact-preview-body pre code')?.textContent).toBe('<draft & safely>');
      expect(view.container.querySelector('.inline-artifact-preview-body draft')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('renders a scripted live iframe for HTML when an agentTaskId is available', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('htmlSource', '<html><body>hi</body></html>'));
    const view = mount(artifact(), 'standalone', transport, {}, { agentTaskId: 'task-1', rootTaskId: 'task-1' });

    try {
      await flushPreview();
      const frame = view.container.querySelector('iframe');
      expect(frame).not.toBeNull();
      expect(frame?.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin');
      expect(frame?.getAttribute('src')).toContain('basil-inline-preview://local');
      expect(view.container.querySelector('.inline-artifact-preview-body pre code')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('falls back to escaped source for HTML when no agentTaskId is available', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('htmlSource', '<draft & safely>'));
    const view = mount(artifact(), 'standalone', transport);

    try {
      await flushPreview();
      expect(view.container.querySelector('iframe')).toBeNull();
      expect(view.container.querySelector('.inline-artifact-preview-body pre code')?.textContent).toBe('<draft & safely>');
    } finally {
      view.cleanup();
    }
  });

  it('does not render the browser action for non-HTML documents', () => {
    const onOpenFile = vi.fn();
    const onOpenContainingFolder = vi.fn();
    const onOpenLocalWebPreview = vi.fn();
    const view = mount(artifact({ preview: { capability: 'unsupported' } }), 'standalone', fakeTransport(), { onOpenFile, onOpenContainingFolder, onOpenLocalWebPreview });

    try {
      expect(view.transport.previewFile).not.toHaveBeenCalled();
      expect(view.transport.setInlineNativePreviewFrame).not.toHaveBeenCalled();
      expect(view.container.textContent).toContain('This artifact is not supported by the in-app preview.');
      const buttons = Array.from(view.container.querySelectorAll('button'));
      act(() => {
        buttons.find(button => button.textContent === 'Open File')?.click();
        buttons.find(button => button.textContent === 'Show in Folder')?.click();
      });
      expect(onOpenFile).toHaveBeenCalledWith('/private/reports/résumé-東京.md');
      expect(onOpenContainingFolder).toHaveBeenCalledWith('/private/reports/résumé-東京.md');
      expect(buttons.map(button => button.textContent)).not.toContain('Preview in Browser');
      expect(onOpenLocalWebPreview).not.toHaveBeenCalled();
    } finally {
      view.cleanup();
    }
  });

  it('renders the browser action for a local HTML document', () => {
    const onOpenLocalWebPreview = vi.fn();
    const view = mount(
      artifact({
        displayName: 'report.html',
        localPath: '/private/reports/report.html',
        preview: { capability: 'unsupported' },
      }),
      'standalone',
      fakeTransport(),
      { onOpenLocalWebPreview },
    );

    try {
      act(() => {
        Array.from(view.container.querySelectorAll('button'))
          .find(button => button.textContent === 'Preview in Browser')
          ?.click();
      });
      expect(onOpenLocalWebPreview).toHaveBeenCalledWith('/private/reports/report.html');
    } finally {
      view.cleanup();
    }
  });

  it('does not request pathless, unavailable, or directory artifacts', () => {
    const view = mount(artifact({ localPath: undefined }));

    try {
      expect(view.transport.previewFile).not.toHaveBeenCalled();
      expect(view.transport.setInlineNativePreviewFrame).not.toHaveBeenCalled();
      expect(view.container.textContent).toContain('This artifact does not have a local file to preview.');
      view.render(artifact({ artifactId: 'unavailable', lifecycle: 'unavailable' }));
      expect(view.container.textContent).toContain('This artifact is unavailable for preview.');
      view.render(artifact({ artifactId: 'directory', artifactKind: 'directory' }));
      expect(view.container.textContent).toContain('Only files can be previewed here.');
      expect(view.transport.previewFile).not.toHaveBeenCalled();
    } finally {
      view.cleanup();
    }
  });

  it('renders a native payload error verbatim before any unsupported fallback', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('unsupported', undefined, 'The file could not be found.'));
    const view = mount(artifact(), 'standalone', transport);

    try {
      await flushPreview();
      expect(transport.setInlineNativePreviewFrame).not.toHaveBeenCalled();
      expect(view.container.textContent).toContain('The file could not be found.');
      expect(view.container.textContent).not.toContain('This file type is not supported by the in-app preview.');
    } finally {
      view.cleanup();
    }
  });

  it('renders the existing bridge timeout rejection and provides an explicit retry', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>)
      .mockRejectedValueOnce(new Error('File preview request timed out.'))
      .mockResolvedValueOnce(payload('text', 'Recovered preview'));
    const view = mount(artifact(), 'standalone', transport);

    try {
      await flushPreview();
      expect(transport.setInlineNativePreviewFrame).not.toHaveBeenCalled();
      expect(view.container.textContent).toContain('File preview request timed out.');
      const retry = Array.from(view.container.querySelectorAll('button')).find(button => button.textContent === 'Retry preview');
      act(() => {
        retry?.click();
      });
      await flushPreview();
      expect(transport.previewFile).toHaveBeenCalledTimes(2);
      expect(view.container.querySelector('.inline-artifact-preview-body pre code')?.textContent).toBe('Recovered preview');
    } finally {
      view.cleanup();
    }
  });

  it('ignores a stale completion after the selected artifact changes', async () => {
    const transport = fakeTransport();
    const first = deferred<FilePreviewPayload>();
    const second = deferred<FilePreviewPayload>();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const firstArtifact = artifact({ artifactId: 'first', displayName: 'first.md', localPath: '/private/first.md' });
    const secondArtifact = artifact({ artifactId: 'second', displayName: 'second.txt', localPath: '/private/second.txt' });
    const view = mount(firstArtifact, 'standalone', transport);

    try {
      view.render(secondArtifact);
      await act(async () => {
        second.resolve(payload('text', 'second content'));
        await Promise.resolve();
      });
      await act(async () => {
        first.resolve(payload('markdown', '# first content'));
        await Promise.resolve();
      });
      expect(view.container.textContent).toContain('second.txt');
      expect(view.container.textContent).toContain('second content');
      expect(view.container.textContent).not.toContain('first content');
      expect(view.container.querySelector('.inline-artifact-preview-body .result-section')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('ignores a stale rejection after the selected artifact changes', async () => {
    const transport = fakeTransport();
    const first = deferred<FilePreviewPayload>();
    const second = deferred<FilePreviewPayload>();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const firstArtifact = artifact({ artifactId: 'first', displayName: 'first.md', localPath: '/private/first.md' });
    const secondArtifact = artifact({ artifactId: 'second', displayName: 'second.txt', localPath: '/private/second.txt' });
    const view = mount(firstArtifact, 'standalone', transport);

    try {
      view.render(secondArtifact);
      await act(async () => {
        second.resolve(payload('text', 'second content'));
        await Promise.resolve();
      });
      await act(async () => {
        first.reject(new Error('first preview request timed out.'));
        await Promise.resolve();
      });
      expect(view.container.textContent).toContain('second.txt');
      expect(view.container.textContent).toContain('second content');
      expect(view.container.textContent).not.toContain('first preview request timed out.');
      expect(view.container.textContent).not.toContain('Retry preview');
    } finally {
      view.cleanup();
    }
  });

  it('does not update an unmounted preview after its bridge request settles', async () => {
    const transport = fakeTransport();
    const request = deferred<FilePreviewPayload>();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockReturnValueOnce(request.promise);
    const view = mount(artifact(), 'standalone', transport);

    view.cleanup();
    await act(async () => {
      request.resolve(payload('text', 'late content'));
      await Promise.resolve();
    });

    expect(view.container.textContent).toBe('');
  });

  it('updates a ready text preview in place for its active bridge request', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ...payload('text', 'First revision'),
      requestId: 'preview-text',
    });
    const view = mount(artifact({ displayName: 'notes.txt', localPath: '/private/fixture/notes.txt' }), 'standalone', transport);

    try {
      await flushPreview();
      const registerCalls = (transport.registerFilePreviewUpdateHandler as ReturnType<typeof vi.fn>).mock.calls;
      const updateHandler = registerCalls[registerCalls.length - 1]?.[0];
      expect(typeof updateHandler).toBe('function');

      act(() => {
        updateHandler({
          ...payload('text', 'Second revision'),
          requestId: 'preview-text',
        });
      });

      expect(view.container.textContent).toContain('Second revision');
      expect(transport.previewFile).toHaveBeenCalledTimes(1);
    } finally {
      view.cleanup();
    }
  });

  it('ignores a live update from a previously selected preview request', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ...payload('text', 'First revision'), requestId: 'preview-first' })
      .mockResolvedValueOnce({ ...payload('text', 'Second revision'), requestId: 'preview-second' });
    const view = mount(artifact({ artifactId: 'first', localPath: '/private/fixture/first.txt' }), 'standalone', transport);

    try {
      await flushPreview();
      const registerCalls = (transport.registerFilePreviewUpdateHandler as ReturnType<typeof vi.fn>).mock.calls;
      const updateHandler = registerCalls[registerCalls.length - 1]?.[0];
      view.render(artifact({ artifactId: 'second', localPath: '/private/fixture/second.txt' }));
      await flushPreview();

      act(() => {
        updateHandler({
          ...payload('text', 'Stale revision'),
          requestId: 'preview-first',
        });
      });

      expect(view.container.textContent).toContain('Second revision');
      expect(view.container.textContent).not.toContain('Stale revision');
    } finally {
      view.cleanup();
    }
  });

  it('renders a native PDF slot, reports geometry, and invokes the preview-window action prop on demand', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      requestId: 'pdf-preview-request',
      path: '/private/fixture/report.pdf',
      name: 'report.pdf',
      kind: 'pdf',
    });
    const onOpenPreviewWindow = vi.fn();
    const view = mount(
      artifact({ displayName: 'report.pdf', localPath: '/private/fixture/report.pdf', preview: { capability: 'supported', kind: 'pdf' } }),
      'standalone',
      transport,
      { onOpenPreviewWindow },
    );

    try {
      await flushPreview();
      expect(view.container.textContent).toContain('Rendering native PDF preview.');
      expect(onOpenPreviewWindow).not.toHaveBeenCalled();
      const previewWindowButton = Array.from(view.container.querySelectorAll('button'))
        .find(button => button.textContent === 'Open Preview Window');
      act(() => {
        previewWindowButton?.click();
      });
      expect(onOpenPreviewWindow).toHaveBeenCalledWith('/private/fixture/report.pdf');
      expect(transport.setInlineNativePreviewFrame).toHaveBeenCalledWith(
        'pdf-preview-request',
        expect.objectContaining({ width: 320, height: 180 }),
      );

      (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce(payload('text', 'plain text'));
      view.render(artifact({
        displayName: 'notes.txt',
        localPath: '/private/fixture/notes.txt',
        preview: { capability: 'supported' },
      }));
      await flushPreview();
      expect(transport.clearInlineNativePreview).toHaveBeenCalledWith('pdf-preview-request');
    } finally {
      view.cleanup();
    }
  });

  it('updates a ready PDF without requesting a second native preview slot', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      requestId: 'pdf-preview-request',
      path: '/private/fixture/report.pdf',
      name: 'report.pdf',
      kind: 'pdf',
    });
    const view = mount(
      artifact({ displayName: 'report.pdf', localPath: '/private/fixture/report.pdf', preview: { capability: 'supported', kind: 'pdf' } }),
      'standalone',
      transport,
    );

    try {
      await flushPreview();
      const registerCalls = (transport.registerFilePreviewUpdateHandler as ReturnType<typeof vi.fn>).mock.calls;
      const updateHandler = registerCalls[registerCalls.length - 1]?.[0];
      const nativeSlotRequests = (transport.setInlineNativePreviewFrame as ReturnType<typeof vi.fn>).mock.calls.length;

      act(() => {
        updateHandler({
          requestId: 'pdf-preview-request',
          path: '/private/fixture/report.pdf',
          name: 'report.pdf',
          kind: 'pdf',
        });
      });

      expect(transport.previewFile).toHaveBeenCalledTimes(1);
      expect(transport.setInlineNativePreviewFrame).toHaveBeenCalledTimes(nativeSlotRequests);
    } finally {
      view.cleanup();
    }
  });

  it('clears a ready preview observer when the preview unmounts', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ...payload('text', 'Ready'),
      requestId: 'preview-clear',
    });
    const view = mount(artifact({ displayName: 'notes.txt', localPath: '/private/fixture/notes.txt' }), 'standalone', transport);

    await flushPreview();
    view.cleanup();

    expect(transport.clearFilePreview).toHaveBeenCalledWith('preview-clear');
  });

  it('clears outgoing preview ownership before the replacement preview starts', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ ...payload('text', 'First preview'), requestId: 'preview-first' })
      .mockResolvedValueOnce({ ...payload('text', 'Second preview'), requestId: 'preview-second', path: '/private/second.txt', name: 'second.txt' });
    const view = mount(artifact(), 'standalone', transport);

    try {
      await flushPreview();
      view.render(artifact({ artifactId: 'second', displayName: 'second.txt', localPath: '/private/second.txt' }));
      await flushPreview();

      expect(transport.clearFilePreview).toHaveBeenCalledWith('preview-first');
    } finally {
      view.cleanup();
    }
  });

  it('does not request a second preview when hydration only changes artifact metadata', async () => {
    const transport = fakeTransport();
    (transport.previewFile as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      requestId: 'pdf-preview-request',
      path: '/private/fixture/report.pdf',
      name: 'report.pdf',
      kind: 'pdf',
    });
    const view = mount(
      artifact({
        artifactId: 'legacy:/private/fixture/report.pdf',
        displayName: 'report.pdf',
        localPath: '/private/fixture/report.pdf',
        preview: { capability: 'unknown' },
      }),
      'standalone',
      transport,
    );

    try {
      await flushPreview();
      expect(transport.previewFile).toHaveBeenCalledTimes(1);
      expect(view.container.textContent).toContain('Rendering native PDF preview.');

      view.render(artifact({
        artifactId: 'artifact-report',
        displayName: 'report.pdf',
        localPath: '/private/fixture/report.pdf',
        lifecycle: 'verified',
        preview: { capability: 'supported', kind: 'pdf' },
        verification: { status: 'verified' },
      }));
      await flushPreview();
      expect(transport.previewFile).toHaveBeenCalledTimes(1);
    } finally {
      view.cleanup();
    }
  });
});
