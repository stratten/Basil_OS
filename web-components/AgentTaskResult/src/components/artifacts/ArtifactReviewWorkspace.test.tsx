// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import type { DerivedAgentTaskArtifact } from './artifactDerivation';

vi.mock('../../services/api', () => ({
  listArtifactRevisions: vi.fn(),
  getArtifactRevision: vi.fn(),
  getBaseUrl: vi.fn(() => ''),
}));

vi.mock('./managedHistory/managedHistoryApi', () => ({
  listManagedFileVersions: vi.fn(),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

import { listArtifactRevisions, getArtifactRevision } from '../../services/api';
import {
  getManagedFileVersionContent,
  listManagedFileVersions,
  restoreManagedFileVersion,
  type ManagedFileVersion,
} from './managedHistory/managedHistoryApi';
import { ArtifactReviewWorkspace } from './ArtifactReviewWorkspace';
import type { ArtifactPreviewTransport } from './transport/artifactPreviewTransport';

function fakeTransport(): ArtifactPreviewTransport {
  return {
    previewFile: vi.fn().mockResolvedValue({ requestId: 'req-1', path: '', name: '', kind: 'unsupported' }),
    clearFilePreview: vi.fn(),
    registerFilePreviewUpdateHandler: vi.fn().mockReturnValue(() => {}),
    setInlineNativePreviewFrame: vi.fn(),
    hideInlineNativePreview: vi.fn(),
    clearInlineNativePreview: vi.fn(),
  };
}

function markdownArtifact(overrides: Partial<DerivedAgentTaskArtifact> = {}): DerivedAgentTaskArtifact {
  return {
    artifactId: 'file-0123456789abcdef01234567',
    displayName: 'report.md',
    localPath: '/tmp/report.md',
    artifactKind: 'file',
    operation: 'create',
    lifecycle: 'verified',
    preview: { capability: 'unknown' },
    verification: { status: 'verified' },
    group: 'produced',
    review: { revision: null, revisionCount: 0, kind: 'markdown', snapshotStatus: 'unavailable' },
    ...overrides,
  };
}

function managedVersion(overrides: Partial<ManagedFileVersion> = {}): ManagedFileVersion {
  return {
    id: 'change-1',
    rootTaskId: 'root-1',
    agentTaskId: 'root-1',
    canonicalPath: '/tmp/report.md',
    operation: 'create',
    origin: 'model',
    postImageSizeBytes: 5,
    restoresChangeId: null,
    createdAt: '2026-08-10T00:00:00Z',
    appliedAt: '2026-08-10T00:00:00Z',
    ...overrides,
  };
}

let container: HTMLDivElement;

beforeAll(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
});

afterEach(() => {
  vi.clearAllMocks();
});

async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('ArtifactReviewWorkspace', () => {
  it('prefers managed history over the task-owned snapshot fallback and selects the focused run', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-2', agentTaskId: 'run-2', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
      managedVersion({ id: 'change-1', agentTaskId: 'run-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockImplementation(async (changeId: string) => ({
      changeId,
      canonicalPath: '/tmp/report.md',
      content: changeId === 'change-2' ? '# v2\n' : '# v1\n',
      truncated: false,
      byteSize: 10,
    }));

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-2"
          rootTaskId="root-1"
          focusedRunId="run-2"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listManagedFileVersions).toHaveBeenCalledWith('/tmp/report.md');
    expect(listArtifactRevisions).not.toHaveBeenCalled();
    expect(container.querySelector('.artifact-review-mode.is-active')?.textContent).toBe('Render');
    expect(container.querySelector('.artifact-review-version-select')).not.toBeNull();
    const selectedOption = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
    expect(selectedOption.getAttribute('data-value')).toBe('0');
    expect(container.querySelector('.artifact-review-restore')).toBeNull();
    expect(container.textContent).toContain('v2');

    act(() => root.unmount());
  });

  it('selects the earlier managed version for an earlier focused run and shows Restore', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-2', agentTaskId: 'run-2', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
      managedVersion({ id: 'change-1', agentTaskId: 'run-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockImplementation(async (changeId: string) => ({
      changeId,
      canonicalPath: '/tmp/report.md',
      content: changeId === 'change-2' ? '# v2\n' : '# v1\n',
      truncated: false,
      byteSize: 10,
    }));

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-1"
          rootTaskId="root-1"
          focusedRunId="run-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
    expect(select.getAttribute('data-value')).toBe('1');
    expect(container.querySelector('.artifact-review-restore')).not.toBeNull();
    expect(container.textContent).toContain('v1');

    act(() => root.unmount());
  });

  it('renders the field-trial two-version managed chain without requesting a task-owned revision that only has one snapshot per endpoint', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-2', rootTaskId: 'root-1', agentTaskId: 'follow-up-1', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
      managedVersion({ id: 'change-1', rootTaskId: 'root-1', agentTaskId: 'root-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockImplementation(async (changeId: string) => ({
      changeId,
      canonicalPath: '/tmp/report.md',
      content: changeId === 'change-2' ? '# follow-up write\n' : '# root write\n',
      truncated: false,
      byteSize: 10,
    }));
    (listArtifactRevisions as ReturnType<typeof vi.fn>).mockResolvedValue({
      revisions: [
        { revision: 1, display_name: 'report.md', content_kind: 'markdown', byte_count: 5, created_at: '2026-08-16T00:01:00Z' },
      ],
    });

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="follow-up-1"
          rootTaskId="root-1"
          focusedRunId="follow-up-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listManagedFileVersions).toHaveBeenCalledWith('/tmp/report.md');
    expect(listArtifactRevisions).not.toHaveBeenCalled();
    expect(getArtifactRevision).not.toHaveBeenCalled();
    const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
    expect(select.getAttribute('data-option-count')).toBe('2');
    expect(select.getAttribute('data-value')).toBe('0');
    expect(container.textContent).toContain('follow-up write');

    act(() => root.unmount());
  });

  it('falls back to task-owned snapshots when managed history has no versions', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (listArtifactRevisions as ReturnType<typeof vi.fn>).mockResolvedValue({
      revisions: [
        { revision: 2, display_name: 'report.md', content_kind: 'markdown', byte_count: 9, created_at: '2026-08-10T00:00:01Z' },
        { revision: 1, display_name: 'report.md', content_kind: 'markdown', byte_count: 5, created_at: '2026-08-10T00:00:00Z' },
      ],
    });
    (getArtifactRevision as ReturnType<typeof vi.fn>).mockImplementation(
      async (_taskId: string, _artifactId: string, revision: number) => (
        revision === 2
          ? { revision: 2, display_name: 'report.md', content_kind: 'markdown', byte_count: 9, created_at: '2026-08-10T00:00:01Z', content: '# v2\n', content_sha256: 'b'.repeat(64) }
          : { revision: 1, display_name: 'report.md', content_kind: 'markdown', byte_count: 5, created_at: '2026-08-10T00:00:00Z', content: '# v1\n', content_sha256: 'a'.repeat(64) }
      )
    );

    const artifact = markdownArtifact({ review: { revision: 2, revisionCount: 2, kind: 'markdown', snapshotStatus: 'available' } });
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="task-1"
          rootTaskId="task-1"
          focusedRunId="task-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listManagedFileVersions).not.toHaveBeenCalled();
    expect(listArtifactRevisions).toHaveBeenCalledWith('task-1', artifact.artifactId);
    expect(getArtifactRevision).toHaveBeenCalledWith('task-1', artifact.artifactId, 2);
    expect(getArtifactRevision).toHaveBeenCalledWith('task-1', artifact.artifactId, 1);
    expect(container.querySelector('.artifact-review-version-select')).toBeNull();
    expect(container.querySelector('.artifact-review-diff')).toBeNull();

    act(() => root.unmount());
  });

  it('shows a retryable in-workspace error when the managed-history transport fails, without a false-empty fallback', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('API GET /... failed: 500'));

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="task-1"
          rootTaskId="task-1"
          focusedRunId="task-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listArtifactRevisions).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('500');
    const retry = container.querySelector<HTMLButtonElement>('.artifact-review-retry');
    expect(retry?.textContent).toBe('Retry');
    await act(async () => {
      retry?.click();
    });
    await flush();
    expect(listManagedFileVersions).toHaveBeenCalledTimes(2);

    act(() => root.unmount());
  });

  it('uses managed history when the task-owned snapshot is unavailable for an otherwise text-reviewable artifact', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-1', agentTaskId: 'run-1' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockResolvedValue({
      changeId: 'change-1',
      canonicalPath: '/tmp/report.md',
      content: '# Managed document\n',
      truncated: false,
      byteSize: 19,
    });

    const artifact = markdownArtifact({
      review: {
        revision: null,
        revisionCount: 0,
        kind: 'markdown',
        snapshotStatus: 'unavailable',
        unavailableReason: 'The task-owned snapshot is unavailable.',
      },
    });
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-1"
          rootTaskId="root-1"
          focusedRunId="run-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listManagedFileVersions).toHaveBeenCalledWith('/tmp/report.md');
    expect(listArtifactRevisions).not.toHaveBeenCalled();
    expect(container.textContent).toContain('Managed document');

    act(() => root.unmount());
  });

  it('restores an older managed version and selects the new head', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([
        managedVersion({ id: 'change-2', agentTaskId: 'run-2', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
        managedVersion({ id: 'change-1', agentTaskId: 'run-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
      ])
      .mockResolvedValueOnce([
        managedVersion({ id: 'change-3', agentTaskId: 'run-1', operation: 'rollback', createdAt: '2026-08-16T00:02:00Z', restoresChangeId: 'change-1' }),
        managedVersion({ id: 'change-2', agentTaskId: 'run-2', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
        managedVersion({ id: 'change-1', agentTaskId: 'run-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
      ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockImplementation(async (changeId: string) => ({
      changeId,
      canonicalPath: '/tmp/report.md',
      content: changeId === 'change-2' ? '# v2\n' : '# v1\n',
      truncated: false,
      byteSize: 10,
    }));
    (restoreManagedFileVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: true,
      changeId: 'change-3',
      canonicalPath: '/tmp/report.md',
      restoredFromChangeId: 'change-1',
    });

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-1"
          rootTaskId="root-1"
          focusedRunId="run-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    const restoreButton = container.querySelector('.artifact-review-restore') as HTMLButtonElement;
    expect(restoreButton).not.toBeNull();
    await act(async () => {
      restoreButton.click();
    });
    await flush();

    expect(restoreManagedFileVersion).toHaveBeenCalledWith({
      rootTaskId: 'root-1',
      canonicalPath: '/tmp/report.md',
      restoresChangeId: 'change-1',
      agentTaskId: 'run-1',
    });
    expect(container.querySelector('.artifact-review-restore')).toBeNull();
    const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
    expect(select.getAttribute('data-value')).toBe('0');

    act(() => root.unmount());
  });

  it('shows a non-destructive drift error on restore conflict and keeps the current selection', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-2', agentTaskId: 'run-2', operation: 'overwrite', createdAt: '2026-08-16T00:01:00Z' }),
      managedVersion({ id: 'change-1', agentTaskId: 'run-1', operation: 'create', createdAt: '2026-08-16T00:00:00Z' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockImplementation(async (changeId: string) => ({
      changeId,
      canonicalPath: '/tmp/report.md',
      content: changeId === 'change-2' ? '# v2\n' : '# v1\n',
      truncated: false,
      byteSize: 10,
    }));
    (restoreManagedFileVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      success: false,
      error: 'The file was modified outside managed history; refusing to restore.',
      errorType: 'managed_history_drift',
    });

    const artifact = markdownArtifact();
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-1"
          rootTaskId="root-1"
          focusedRunId="run-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    const restoreButton = container.querySelector('.artifact-review-restore') as HTMLButtonElement;
    await act(async () => {
      restoreButton.click();
    });
    await flush();

    expect(container.textContent).toContain('refusing to restore');
    const select = container.querySelector('.artifact-review-version-select') as HTMLButtonElement;
    expect(select.getAttribute('data-value')).toBe('1');

    act(() => root.unmount());
  });

  it('disables the diff toggle when only one revision exists', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    (listArtifactRevisions as ReturnType<typeof vi.fn>).mockResolvedValue({
      revisions: [
        { revision: 1, display_name: 'report.md', content_kind: 'markdown', byte_count: 5, created_at: '2026-08-10T00:00:00Z' },
      ],
    });
    (getArtifactRevision as ReturnType<typeof vi.fn>).mockResolvedValue({
      revision: 1,
      display_name: 'report.md',
      content_kind: 'markdown',
      byte_count: 5,
      created_at: '2026-08-10T00:00:00Z',
      content: '# v1\n',
      content_sha256: 'a'.repeat(64),
    });

    const artifact = markdownArtifact({ review: { revision: 1, revisionCount: 1, kind: 'markdown', snapshotStatus: 'available' } });
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="task-1"
          rootTaskId="task-1"
          focusedRunId="task-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    const diffButton = Array.from(container.querySelectorAll('.artifact-review-mode'))
      .find(button => button.textContent === 'Diff') as HTMLButtonElement | undefined;
    expect(diffButton?.disabled).toBe(true);

    act(() => root.unmount());
  });

  it('falls back to InlineArtifactPreview for a non-text-reviewable artifact', async () => {
    const artifact = markdownArtifact({
      review: { revision: null, revisionCount: 0, snapshotStatus: 'unavailable', unavailableReason: 'Snapshot unavailable: unsupported file type.' },
    });
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="task-1"
          rootTaskId="task-1"
          focusedRunId="task-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    expect(listManagedFileVersions).not.toHaveBeenCalled();
    expect(listArtifactRevisions).not.toHaveBeenCalled();
    expect(container.querySelector('.artifact-review-mode-toggle')).toBeNull();

    act(() => root.unmount());
  });

  it('renders an HTML artifact with a scripted live iframe instead of the inert sandboxed source view', async () => {
    (listManagedFileVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      managedVersion({ id: 'change-1', agentTaskId: 'run-1', canonicalPath: '/tmp/report.html' }),
    ]);
    (getManagedFileVersionContent as ReturnType<typeof vi.fn>).mockResolvedValue({
      changeId: 'change-1',
      canonicalPath: '/tmp/report.html',
      content: '<html><body>hi</body></html>',
      truncated: false,
      byteSize: 10,
    });

    const artifact = markdownArtifact({
      localPath: '/tmp/report.html',
      review: { revision: 1, revisionCount: 1, kind: 'html', snapshotStatus: 'available' },
    });
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <ArtifactReviewWorkspace
          agentTaskId="run-1"
          rootTaskId="root-1"
          focusedRunId="run-1"
          artifacts={[artifact]}
          activeArtifactId={artifact.artifactId}
          onSelectArtifact={() => {}}
          previewTransport={fakeTransport()}
        />
      );
    });
    await flush();

    const frame = container.querySelector('.artifact-review-html-frame') as HTMLIFrameElement | null;
    expect(frame).not.toBeNull();
    expect(frame?.getAttribute('sandbox')).toBe('allow-scripts allow-same-origin');
    expect(frame?.getAttribute('src')).toContain('basil-inline-preview://local/tmp/report.html');
    expect(frame?.hasAttribute('srcdoc')).toBe(false);

    act(() => root.unmount());
  });

});
