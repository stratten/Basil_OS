// @vitest-environment jsdom

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const managedHistoryMocks = vi.hoisted(() => ({
  listManagedFileVersions: vi.fn(),
  getManagedFileVersionContent: vi.fn(),
  restoreManagedFileVersion: vi.fn(),
}));

vi.mock('./managedHistoryApi', () => managedHistoryMocks);

import { useManagedVersionHistory, type UseManagedVersionHistoryParams, type UseManagedVersionHistoryResult } from './useManagedVersionHistory';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function version(id: string, agentTaskId: string) {
  return {
    id,
    rootTaskId: 'root-1',
    agentTaskId,
    canonicalPath: '/tmp/doc.md',
    operation: 'overwrite' as const,
    origin: 'model' as const,
    postImageSizeBytes: 10,
    restoresChangeId: null,
    createdAt: '2026-01-01T00:00:00Z',
    appliedAt: '2026-01-01T00:00:00Z',
  };
}

function content(changeId: string, text: string) {
  return { changeId, canonicalPath: '/tmp/doc.md', content: text, truncated: false, byteSize: text.length };
}

let container: HTMLDivElement;
let latest: UseManagedVersionHistoryResult | undefined;

function TestHarness(props: UseManagedVersionHistoryParams) {
  latest = useManagedVersionHistory(props);
  return null;
}

// Using react-dom directly (no @testing-library) matches this repo's existing
// hook/component test conventions (see FilePreviewApp.test.tsx, bridge.test.ts).
async function renderHook(params: UseManagedVersionHistoryParams) {
  const React = await import('react');
  const root = createRoot(container);
  const rerender = (nextParams: UseManagedVersionHistoryParams) => {
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
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  vi.clearAllMocks();
});

afterEach(() => {
  container.remove();
  latest = undefined;
});

describe('useManagedVersionHistory', () => {
  it('stays idle when disabled or canonicalPath is absent', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c1', 'task-1')]);
    const view = await renderHook({ canonicalPath: undefined, enabled: true });
    await flush();
    try {
      expect(latest?.state.status).toBe('idle');
      expect(managedHistoryMocks.listManagedFileVersions).not.toHaveBeenCalled();
    } finally {
      view.unmount();
    }
  });

  it('reports empty status when the transport returns zero versions', async () => {
    let resolveVersions: ((versions: ReturnType<typeof version>[]) => void) | undefined;
    managedHistoryMocks.listManagedFileVersions.mockImplementationOnce(() => new Promise(resolve => {
      resolveVersions = resolve;
    }));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true });
    await flush();
    try {
      await act(async () => {
        resolveVersions?.([]);
        await Promise.resolve();
      });
      expect(latest?.state.status).toBe('empty');
      expect(latest?.state.versions).toEqual([]);
    } finally {
      view.unmount();
    }
  });

  it('loads the head version content and marks status ready', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true, focusedAgentTaskId: 'unmatched-task' });
    await flush();
    try {
      expect(latest?.state.status).toBe('ready');
      expect(latest?.state.selectedIndex).toBe(0);
      expect(latest?.state.selectedContent).toBe('body-c2');
      expect(latest?.state.compareContent).toBe('body-c1');
    } finally {
      view.unmount();
    }
  });

  it('pre-selects the version matching focusedAgentTaskId when it is not the head', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true, focusedAgentTaskId: 'task-1' });
    await flush();
    try {
      expect(latest?.state.selectedIndex).toBe(1);
      expect(latest?.state.selectedContent).toBe('body-c1');
    } finally {
      view.unmount();
    }
  });

  it('surfaces a transport failure as an error with a retry affordance, and retry re-fetches', async () => {
    let rejectVersions: ((error: Error) => void) | undefined;
    managedHistoryMocks.listManagedFileVersions.mockImplementationOnce(() => new Promise((_resolve, reject) => {
      rejectVersions = reject;
    }));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true });
    await flush();
    try {
      await act(async () => {
        rejectVersions?.(new Error('network down'));
        await Promise.resolve();
      });
      expect(latest?.state.status).toBe('error');
      expect(latest?.state.errorMessage).toBe('network down');

      let resolveRecoveredVersions: ((versions: ReturnType<typeof version>[]) => void) | undefined;
      managedHistoryMocks.listManagedFileVersions.mockImplementationOnce(() => new Promise(resolve => {
        resolveRecoveredVersions = resolve;
      }));
      managedHistoryMocks.getManagedFileVersionContent.mockResolvedValue(content('c1', 'recovered'));
      act(() => { latest?.retry(); });
      await flush();
      await act(async () => {
        resolveRecoveredVersions?.([version('c1', 'task-1')]);
        await Promise.resolve();
      });
      expect(latest?.state.status).toBe('ready');
      expect(latest?.state.selectedContent).toBe('recovered');
    } finally {
      view.unmount();
    }
  });

  it('selectVersion loads the chosen version and its predecessor for diffing', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c3', 'task-3'), version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true });
    await flush();
    try {
      act(() => { latest?.selectVersion(1); });
      await flush();
      expect(latest?.state.selectedIndex).toBe(1);
      expect(latest?.state.selectedContent).toBe('body-c2');
      expect(latest?.state.compareContent).toBe('body-c1');
    } finally {
      view.unmount();
    }
  });

  it('canRestore is false without rootTaskId and true when rootTaskId is supplied', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockResolvedValue(content('c1', 'body'));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true });
    await flush();
    try {
      expect(latest?.canRestore).toBe(false);
      view.rerender({ canonicalPath: '/tmp/doc.md', enabled: true, rootTaskId: 'root-1' });
      await flush();
      expect(latest?.canRestore).toBe(true);
    } finally {
      view.unmount();
    }
  });

  it('restore() is a no-op without rootTaskId', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true });
    await flush();
    try {
      act(() => { latest?.selectVersion(1); });
      await flush();
      act(() => { latest?.restore(); });
      await flush();
      expect(managedHistoryMocks.restoreManagedFileVersion).not.toHaveBeenCalled();
      expect(latest?.state.restoreStatus).toBe('idle');
    } finally {
      view.unmount();
    }
  });

  it('restore() succeeds, re-fetches versions, and resets selection to the new head', async () => {
    managedHistoryMocks.listManagedFileVersions
      .mockResolvedValueOnce([version('c2', 'task-2'), version('c1', 'task-1')])
      .mockResolvedValueOnce([version('c3', 'task-3'), version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    managedHistoryMocks.restoreManagedFileVersion.mockResolvedValue({ success: true, changeId: 'c3' });
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true, rootTaskId: 'root-1', focusedAgentTaskId: 'task-9' });
    await flush();
    try {
      act(() => { latest?.selectVersion(1); });
      await flush();
      act(() => { latest?.restore(); });
      await flush();
      expect(managedHistoryMocks.restoreManagedFileVersion).toHaveBeenCalledWith({
        rootTaskId: 'root-1',
        canonicalPath: '/tmp/doc.md',
        restoresChangeId: 'c1',
        agentTaskId: 'task-9',
      });
      expect(latest?.state.restoreStatus).toBe('idle');
      expect(latest?.state.selectedIndex).toBe(0);
      expect(latest?.state.versions).toHaveLength(3);
      expect(latest?.state.selectedContent).toBe('body-c3');
    } finally {
      view.unmount();
    }
  });

  it('treats an empty post-restore refresh as an empty history rather than dereferencing a missing head version', async () => {
    managedHistoryMocks.listManagedFileVersions
      .mockResolvedValueOnce([version('c2', 'task-2'), version('c1', 'task-1')])
      .mockResolvedValueOnce([]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    managedHistoryMocks.restoreManagedFileVersion.mockResolvedValue({ success: true, changeId: 'c3' });
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true, rootTaskId: 'root-1' });
    await flush();
    try {
      act(() => { latest?.selectVersion(1); });
      await flush();
      act(() => { latest?.restore(); });
      await flush();
      expect(latest?.state.status).toBe('empty');
      expect(latest?.state.restoreStatus).toBe('idle');
    } finally {
      view.unmount();
    }
  });

  it('restore() surfaces a backend-reported failure without mutating versions', async () => {
    managedHistoryMocks.listManagedFileVersions.mockResolvedValue([version('c2', 'task-2'), version('c1', 'task-1')]);
    managedHistoryMocks.getManagedFileVersionContent.mockImplementation((id: string) => Promise.resolve(content(id, `body-${id}`)));
    managedHistoryMocks.restoreManagedFileVersion.mockResolvedValue({ success: false, error: 'Conflicting concurrent edit.' });
    const view = await renderHook({ canonicalPath: '/tmp/doc.md', enabled: true, rootTaskId: 'root-1' });
    await flush();
    try {
      act(() => { latest?.selectVersion(1); });
      await flush();
      act(() => { latest?.restore(); });
      await flush();
      expect(latest?.state.restoreStatus).toBe('error');
      expect(latest?.state.restoreErrorMessage).toBe('Conflicting concurrent edit.');
      expect(latest?.state.selectedIndex).toBe(1);
    } finally {
      view.unmount();
    }
  });
});
