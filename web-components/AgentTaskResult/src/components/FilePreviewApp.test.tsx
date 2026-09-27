// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FilePreviewInitMessage } from '../types';
import type { FilePreviewPayload } from '../services/bridge';

const bridgeMocks = vi.hoisted(() => ({
  closeWidget: vi.fn(),
  minimizeWidget: vi.fn(),
  openContainingFolder: vi.fn(),
  openExternalUrl: vi.fn(),
  openFile: vi.fn(),
  previewFile: vi.fn(),
  clearFilePreview: vi.fn(),
  registerFilePreviewInitHandler: vi.fn(),
  registerFilePreviewUpdateHandler: vi.fn(() => () => {}),
  reportFilePreviewChromeHeight: vi.fn(),
  registerValidationManagedHistoryRestoreHandler: vi.fn(() => () => {}),
}));

const apiMocks = vi.hoisted(() => ({
  setBaseUrl: vi.fn(),
}));

const managedHistoryMocks = vi.hoisted(() => ({
  listManagedFileVersions: vi.fn().mockResolvedValue([]),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

vi.mock('../services/bridge', () => bridgeMocks);
vi.mock('../services/api', () => apiMocks);
vi.mock('./artifacts/managedHistory/managedHistoryApi', () => managedHistoryMocks);

import FilePreviewApp from './FilePreviewApp';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function payload(
  kind: FilePreviewPayload['kind'],
  content?: string,
  error?: string,
): FilePreviewPayload {
  const value: FilePreviewPayload = {
    requestId: 'file-preview-test',
    path: '/private/reports/résumé-東京.md',
    name: 'résumé-東京.md',
    kind,
  };
  if (content !== undefined) value.content = content;
  if (error !== undefined) value.error = error;
  return value;
}

async function renderPreview(filePreviewPayload: FilePreviewPayload) {
  bridgeMocks.previewFile.mockResolvedValueOnce(filePreviewPayload);
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);

  act(() => {
    root.render(<FilePreviewApp />);
  });

  const calls = bridgeMocks.registerFilePreviewInitHandler.mock.calls as Array<[(config: FilePreviewInitMessage) => void]>;
  const handler = calls[calls.length - 1]?.[0];
  if (!handler) throw new Error('Expected preview-init handler registration.');

  await act(async () => {
    handler({ path: filePreviewPayload.path });
    await Promise.resolve();
  });

  return {
    container,
    cleanup: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  managedHistoryMocks.listManagedFileVersions.mockResolvedValue([]);
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FilePreviewApp presentation policy', () => {
  it('keeps the existing initial loading label and body before native initialization', () => {
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);

    try {
      act(() => {
        root.render(<FilePreviewApp />);
      });

      expect(container.textContent).toContain('Loading Preview');
      expect(container.textContent).toContain('Loading preview...');
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it('keeps Markdown payloads on the existing Markdown renderer branch', async () => {
    const view = await renderPreview(payload('markdown', '# Overview'));

    try {
      expect(view.container.textContent).toContain('Markdown Preview');
      expect(view.container.textContent).toContain('Overview');
      expect(view.container.querySelector('.file-preview-window-markdown')).not.toBeNull();
      expect(view.container.querySelector('.file-preview-window-source')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('updates the current preview when native reports a matching file revision', async () => {
    const view = await renderPreview({
      ...payload('text', 'First revision'),
      requestId: 'preview-revision',
    });

    try {
      const updateHandlerCalls = bridgeMocks.registerFilePreviewUpdateHandler.mock.calls as unknown as Array<[(update: unknown) => void]>;
      const updateHandler = updateHandlerCalls[updateHandlerCalls.length - 1]?.[0];
      expect(typeof updateHandler).toBe('function');
      if (!updateHandler) throw new Error('Expected the native preview update handler to be registered.');

      act(() => {
        updateHandler({
          ...payload('text', 'Second revision'),
          requestId: 'preview-revision',
        });
      });

      expect(view.container.querySelector('.file-preview-window-source code')?.textContent).toBe('Second revision');
      expect(bridgeMocks.previewFile).toHaveBeenCalledTimes(1);
    } finally {
      view.cleanup();
    }
  });

  it.each(['text', 'code', 'htmlSource'] as const)('keeps %s payloads escaped in the source branch', async (kind) => {
    const view = await renderPreview(payload(kind, '<draft & safely>'));

    try {
      expect(view.container.querySelector('.file-preview-window-source code')?.textContent).toBe('<draft & safely>');
      expect(view.container.querySelector('.file-preview-window-source draft')).toBeNull();
      expect(view.container.querySelector('.file-preview-window-markdown')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('keeps the native PDF placeholder branch', async () => {
    const view = await renderPreview(payload('pdf'));

    try {
      expect(view.container.textContent).toContain('PDF Preview');
      expect(view.container.querySelector('.file-preview-window-pdf-placeholder')).not.toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('keeps the unsupported fallback branch for a ready unsupported payload', async () => {
    const view = await renderPreview(payload('unsupported'));

    try {
      expect(view.container.textContent).toContain('This file type is not supported by the in-app preview.');
      expect(view.container.querySelector('.file-preview-window-source')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it.each([
    'The file could not be found.',
    'Folders cannot be previewed here.',
    'The file could not be read as UTF-8 text.',
    'This file is too large to preview in the window.',
  ])('renders the native error message without reinterpretation: %s', async (error) => {
    const view = await renderPreview(payload('unsupported', undefined, error));

    try {
      expect(view.container.textContent).toContain(error);
      expect(view.container.textContent).not.toContain('This file type is not supported by the in-app preview.');
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
    canonicalPath: '/private/reports/résumé-東京.md',
    operation: 'overwrite' as const,
    origin: 'model' as const,
    postImageSizeBytes: 10,
    restoresChangeId: null,
    createdAt: '2026-01-01T00:00:00Z',
    appliedAt: '2026-01-01T00:00:00Z',
  };
}

describe('FilePreviewApp managed version parity', () => {
  it('calls setBaseUrl when the init message carries a port, so managed-history HTTP calls can resolve', async () => {
    const view = await renderPreview(payload('markdown', '# Overview'));
    try {
      bridgeMocks.previewFile.mockResolvedValueOnce(payload('markdown', '# Overview'));
      const calls = bridgeMocks.registerFilePreviewInitHandler.mock.calls as Array<[(config: { path: string; port?: number }) => void]>;
      const handler = calls[calls.length - 1]?.[0];
      await act(async () => {
        handler?.({ path: '/private/reports/résumé-東京.md', port: 8123 });
        await Promise.resolve();
      });
      expect(apiMocks.setBaseUrl).toHaveBeenCalledWith(8123);
    } finally {
      view.cleanup();
    }
  });

  it('renders no version controls when the managed-history transport reports zero versions', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([]);
    const view = await renderPreview(payload('markdown', '# Overview'));
    try {
      await act(async () => { await Promise.resolve(); await Promise.resolve(); });
      expect(view.container.querySelector('.artifact-review-version-select')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('renders the version dropdown without a restore button when opened without rootTaskId', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-2'),
      managedVersion('change-1', 'task-1'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/private/reports/résumé-東京.md', content: `content-${id}`, truncated: false, byteSize: 8 }));

    const view = await renderPreview(payload('markdown', '# Overview'));
    try {
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(view.container.querySelector('.artifact-review-version-select')).not.toBeNull();
      expect(view.container.querySelector('.artifact-review-restore')).toBeNull();
    } finally {
      view.cleanup();
    }
  });

  it('shows the restore button for a non-head selection when the init message carried a rootTaskId', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-2'),
      managedVersion('change-1', 'task-1'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/private/reports/résumé-東京.md', content: `content-${id}`, truncated: false, byteSize: 8 }));

    bridgeMocks.previewFile.mockResolvedValueOnce(payload('markdown', '# Overview'));
    const container = document.createElement('div');
    document.body.appendChild(container);
    const root = createRoot(container);
    act(() => { root.render(<FilePreviewApp />); });
    const calls = bridgeMocks.registerFilePreviewInitHandler.mock.calls as Array<[(config: { path: string; rootTaskId?: string }) => void]>;
    const handler = calls[calls.length - 1]?.[0];
    await act(async () => {
      handler?.({ path: '/private/reports/résumé-東京.md', rootTaskId: 'root-1' });
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    try {
      const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement | null;
      expect(select).not.toBeNull();
      act(() => { select!.click(); });
      const option = document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option')[1];
      act(() => { option.click(); });
      expect(container.querySelector('.artifact-review-restore')).not.toBeNull();
    } finally {
      act(() => root.unmount());
      container.remove();
    }
  });

  it('keeps stale content out of the body while the newly selected version is loading', async () => {
    let resolveSelectedContent: ((value: { changeId: string; canonicalPath: string; content: string; truncated: boolean; byteSize: number }) => void) | undefined;
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([
      managedVersion('change-2', 'task-2'),
      managedVersion('change-1', 'task-1'),
    ]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => {
      if (id === 'change-2') {
        return Promise.resolve({ changeId: id, canonicalPath: '/private/reports/résumé-東京.md', content: 'current version', truncated: false, byteSize: 15 });
      }
      if (resolveSelectedContent) {
        return new Promise(resolve => { resolveSelectedContent = resolve; });
      }
      return Promise.resolve({ changeId: id, canonicalPath: '/private/reports/résumé-東京.md', content: 'older version', truncated: false, byteSize: 13 });
    });

    const view = await renderPreview(payload('text', 'disk version'));
    try {
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      const select = view.container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
      resolveSelectedContent = () => undefined;
      act(() => { select.click(); });
      const option = document.querySelectorAll<HTMLButtonElement>('.tokenized-select__option')[1];
      act(() => { option.click(); });
      const activeLayer = view.container.querySelector('.file-preview-window-body-layer[data-presence-phase="present"]');
      expect(activeLayer?.textContent).toContain('Loading selected version...');
      expect(activeLayer?.textContent).not.toContain('current version');
    } finally {
      view.cleanup();
    }
  });

  it('refreshes managed history after the native preview reports a matching file update', async () => {
    managedHistoryMocks.listManagedFileVersions
      .mockResolvedValueOnce([managedVersion('change-1', 'task-1')])
      .mockResolvedValueOnce([managedVersion('change-2', 'task-1'), managedVersion('change-1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) =>
      Promise.resolve({ changeId: id, canonicalPath: '/private/reports/résumé-東京.md', content: `content-${id}`, truncated: false, byteSize: 8 }));

    const view = await renderPreview({
      ...payload('text', 'first disk version'),
      requestId: 'preview-revision',
    });
    try {
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      const updateHandlerCalls = bridgeMocks.registerFilePreviewUpdateHandler.mock.calls as unknown as Array<[(update: FilePreviewPayload) => void]>;
      const updateHandler = updateHandlerCalls[updateHandlerCalls.length - 1]?.[0];
      act(() => {
        updateHandler?.({
          ...payload('text', 'second disk version'),
          requestId: 'preview-revision',
        });
      });
      await act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); });
      expect(managedHistoryMocks.listManagedFileVersions).toHaveBeenCalledTimes(2);
      expect(view.container.querySelector('.file-preview-window-body-layer[data-presence-phase="present"] .file-preview-window-source code')?.textContent).toBe('content-change-2');
    } finally {
      view.cleanup();
    }
  });
});
