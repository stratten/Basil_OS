// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ConversationArtifactPreviewSidebar from './ConversationArtifactPreviewSidebar';
import type { ConversationArtifactPreviewSelection } from './conversationArtifactPreviewState';

const apiMocks = vi.hoisted(() => ({ getConversationAgentTaskDetail: vi.fn() }));
vi.mock('../../services/api', () => apiMocks);

const bridgeMocks = vi.hoisted(() => ({
  checkConversationArtifactPreviewAvailability: vi.fn().mockResolvedValue(new Set<string>()),
  openConversationArtifactFile: vi.fn(),
  openConversationArtifactContainingFolder: vi.fn(),
  openConversationArtifactPreviewWindow: vi.fn(),
  openConversationStaticLocalWebPreview: vi.fn(),
  openConversationLocalServerPreview: vi.fn(),
}));
vi.mock('../../services/artifactPreviewBridge', () => bridgeMocks);

const agentTaskApiMocks = vi.hoisted(() => ({
  listArtifactRevisions: vi.fn(),
  getArtifactRevision: vi.fn(),
}));
vi.mock('@agent-task/services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@agent-task/services/api')>();
  return { ...actual, ...agentTaskApiMocks };
});

const managedHistoryApiMocks = vi.hoisted(() => ({
  listManagedFileVersions: vi.fn().mockResolvedValue([]),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));
vi.mock('@agent-task/components/artifacts/managedHistory/managedHistoryApi', () => managedHistoryApiMocks);

function fakeTransport() {
  return {
    previewFile: vi.fn().mockResolvedValue({ requestId: 'req-1', path: '', name: '', kind: 'unsupported' }),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn().mockReturnValue(() => {}),
    setInlineNativePreviewFrame: vi.fn(),
    hideInlineNativePreview: vi.fn(),
    clearInlineNativePreview: vi.fn(),
  };
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    original_prompt: 'Draft the report',
    transcribed_prompt: 'Draft the report',
    timestamp: '2026-08-10T00:00:00Z',
    status: 'completed',
    files: [{
      name: 'report.md',
      path: '/private/reports/report.md',
      kind: 'file',
      operation: 'create',
      artifact: {
        artifact_id: 'artifact-1',
        display_name: 'report.md',
        local_path: '/private/reports/report.md',
        artifact_kind: 'file',
        operation: 'create',
        lifecycle: 'ready',
        preview: { capability: 'unknown' },
        verification: { status: 'unknown' },
        review: { revision: 1, revision_count: 1, kind: 'markdown', snapshot_status: 'available' },
      },
    }],
    reference_paths: [],
    follow_ups: [],
    ...overrides,
  };
}

let container: HTMLDivElement;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  apiMocks.getConversationAgentTaskDetail.mockReset();
  bridgeMocks.checkConversationArtifactPreviewAvailability.mockReset().mockResolvedValue(new Set<string>());
  bridgeMocks.openConversationArtifactFile.mockReset();
  bridgeMocks.openConversationArtifactContainingFolder.mockReset();
  bridgeMocks.openConversationArtifactPreviewWindow.mockReset();
  bridgeMocks.openConversationStaticLocalWebPreview.mockReset();
  bridgeMocks.openConversationLocalServerPreview.mockReset();
  managedHistoryApiMocks.listManagedFileVersions.mockReset().mockResolvedValue([]);
  managedHistoryApiMocks.getManagedFileVersionContent.mockReset();
  managedHistoryApiMocks.restoreManagedFileVersion.mockReset();
  agentTaskApiMocks.listArtifactRevisions.mockReset().mockResolvedValue({
    revisions: [{
      revision: 1,
      display_name: 'report.md',
      content_kind: 'markdown',
      byte_count: 16,
      created_at: '2026-08-10T00:00:00Z',
    }],
  });
  agentTaskApiMocks.getArtifactRevision.mockReset().mockResolvedValue({
    revision: 1,
    display_name: 'report.md',
    content_kind: 'markdown',
    byte_count: 16,
    created_at: '2026-08-10T00:00:00Z',
    content: '# Stored report',
    content_sha256: 'abc',
  });
});

afterEach(() => {
  container.remove();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function selection(overrides: Partial<ConversationArtifactPreviewSelection> = {}): ConversationArtifactPreviewSelection {
  return { conversationId: 'conv-1', agentTaskId: 'task-1', ...overrides };
}

describe('ConversationArtifactPreviewSidebar', () => {
  it('loads the task, selects the first eligible artifact, and renders the review workspace', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail());
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(apiMocks.getConversationAgentTaskDetail).toHaveBeenCalledWith('task-1');
    expect(container.querySelector('.chats-artifact-sidebar-document-title')?.textContent).toBe('report.md');
    expect(container.querySelector('.artifact-review-workspace')).not.toBeNull();
    expect(agentTaskApiMocks.listArtifactRevisions).toHaveBeenCalledWith('task-1', 'artifact-1');
    expect(agentTaskApiMocks.getArtifactRevision).toHaveBeenCalledWith('task-1', 'artifact-1', 1);
    expect(container.textContent).toContain('Stored report');

    act(() => root.unmount());
  });

  it('shows an explicit empty state when the task has no eligible documents', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail({ files: [] }));
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(container.textContent).toContain('No documents are currently available to preview.');

    act(() => root.unmount());
  });

  it('shows an explicit error state when the task detail request fails', async () => {
    apiMocks.getConversationAgentTaskDetail.mockRejectedValue(new Error('Network unavailable'));
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Network unavailable');

    act(() => root.unmount());
  });

  it('excludes a produced artifact with no stored revision whose live path is not confirmed available', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail({
      files: [{
        name: 'draft.md',
        path: '/private/reports/draft.md',
        kind: 'file',
        operation: 'create',
        artifact: {
          artifact_id: 'artifact-2',
          display_name: 'draft.md',
          local_path: '/private/reports/draft.md',
          artifact_kind: 'file',
          operation: 'create',
          lifecycle: 'ready',
          preview: { capability: 'unknown' },
          verification: { status: 'unknown' },
        },
      }],
    }));
    bridgeMocks.checkConversationArtifactPreviewAvailability.mockResolvedValue(new Set<string>());
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(container.textContent).toContain('No documents are currently available to preview.');

    act(() => root.unmount());
  });

  it('keeps a durable artifact previewable when the native availability probe fails', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail());
    bridgeMocks.checkConversationArtifactPreviewAvailability.mockRejectedValue(new Error('Native bridge unavailable'));
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(container.querySelector('.chats-artifact-sidebar-document-title')?.textContent).toBe('report.md');

    act(() => root.unmount());
  });

  it('reports a selected artifact that is absent from the task detail', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail());
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection({ artifactId: 'artifact-from-another-task' })}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    expect(container.querySelector('[role="alert"]')?.textContent).toBe('The selected document is no longer available to preview.');

    act(() => root.unmount());
  });

  it('invokes the close handler from the sidebar close control', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail());
    const onClose = vi.fn();
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={onClose}
        />,
      );
    });
    await flush();

    act(() => {
      (container.querySelector('.chats-artifact-sidebar-close') as HTMLButtonElement)?.click();
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    act(() => root.unmount());
  });

  it('exposes no browser preview action for Markdown and supports keyboard sidebar resizing', async () => {
    apiMocks.getConversationAgentTaskDetail.mockResolvedValue(detail());
    const root = createRoot(container);

    await act(async () => {
      root.render(
        <ConversationArtifactPreviewSidebar
          selection={selection()}
          transport={fakeTransport()}
          onSelectArtifact={() => {}}
          onClose={() => {}}
        />,
      );
    });
    await flush();

    act(() => {
      (container.querySelector('[aria-label="Open File"]') as HTMLButtonElement)?.click();
      (container.querySelector('[aria-label="Show in Folder"]') as HTMLButtonElement)?.click();
      (container.querySelector('[aria-label="Open Preview Window"]') as HTMLButtonElement)?.click();
    });
    expect(bridgeMocks.openConversationArtifactFile).toHaveBeenCalledWith('/private/reports/report.md');
    expect(bridgeMocks.openConversationArtifactContainingFolder).toHaveBeenCalledWith('/private/reports/report.md');
    expect(bridgeMocks.openConversationArtifactPreviewWindow).toHaveBeenCalledWith('/private/reports/report.md');
    expect(container.querySelector('[aria-label="Preview static page"]')).toBeNull();
    expect(bridgeMocks.openConversationStaticLocalWebPreview).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-label="Preview with local server"]')).toBeNull();
    expect(bridgeMocks.openConversationLocalServerPreview).not.toHaveBeenCalled();

    const resizeHandle = container.querySelector<HTMLDivElement>('.chats-artifact-sidebar-resize-handle');
    expect(resizeHandle?.getAttribute('role')).toBe('separator');
    expect(resizeHandle?.getAttribute('aria-valuenow')).toBe('420');
    act(() => {
      resizeHandle?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft', bubbles: true }));
    });
    expect(container.querySelector<HTMLElement>('.chats-artifact-sidebar')?.style.getPropertyValue('--chats-artifact-sidebar-width')).toBe('444px');

    act(() => root.unmount());
  });
});
