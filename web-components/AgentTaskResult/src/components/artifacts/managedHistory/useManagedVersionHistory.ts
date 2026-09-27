import { useEffect, useRef, useState } from 'react';
import {
  getManagedFileVersionContent,
  listManagedFileVersions,
  restoreManagedFileVersion,
  type ManagedFileVersion,
} from './managedHistoryApi';

export type ManagedVersionHistoryStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error';
export type ManagedVersionRestoreStatus = 'idle' | 'restoring' | 'error';

export interface ManagedVersionHistoryState {
  status: ManagedVersionHistoryStatus;
  errorMessage?: string;
  versions: ManagedFileVersion[];
  selectedIndex: number;
  selectedContent?: string;
  compareContent?: string;
  restoreStatus: ManagedVersionRestoreStatus;
  restoreErrorMessage?: string;
}

export interface UseManagedVersionHistoryParams {
  /** Absolute on-disk path the managed-history backend keys versions by. */
  canonicalPath: string | undefined;
  /** Gate: when false, the hook stays idle and issues no requests. */
  enabled: boolean;
  /** Required to enable restore; when absent, `canRestore` is false. */
  rootTaskId?: string;
  /**
   * The run whose version should be pre-selected when multiple versions
   * exist (matched against `ManagedFileVersion.agentTaskId`). Also sent as
   * restore provenance. Falls back to index 0 ("Current") when absent or
   * unmatched.
   */
  focusedAgentTaskId?: string;
  /**
   * Extra dependency that forces a re-fetch when it changes, even if
   * `canonicalPath` is unchanged (e.g. the sidebar bumps this when a new
   * revision is recorded for the currently-viewed artifact).
   */
  refreshKey?: string | number;
}

export interface UseManagedVersionHistoryResult {
  state: ManagedVersionHistoryState;
  /** True only when `rootTaskId` was supplied; gates the restore button. */
  canRestore: boolean;
  selectVersion: (index: number) => void;
  restore: () => void;
  retry: () => void;
}

const EMPTY_STATE: ManagedVersionHistoryState = {
  status: 'idle',
  versions: [],
  selectedIndex: 0,
  restoreStatus: 'idle',
};

async function loadContentAt(
  versions: ManagedFileVersion[],
  index: number,
): Promise<{ selectedContent: string; compareContent?: string }> {
  const selected = versions[index];
  const older = versions[index + 1];
  const [selectedResult, olderResult] = await Promise.all([
    getManagedFileVersionContent(selected.id),
    older ? getManagedFileVersionContent(older.id) : Promise.resolve(undefined),
  ]);
  if (selectedResult.truncated) {
    throw new Error('This version is too large to display in the review workspace.');
  }
  return {
    selectedContent: selectedResult.content ?? '',
    compareContent: olderResult && !olderResult.truncated ? olderResult.content ?? '' : undefined,
  };
}

/**
 * Owns the fetch/select/restore/retry state machine for one canonical
 * file's managed version history. Used by ArtifactReviewWorkspace (the
 * sidebar's document review panel), FilePreviewApp (the detached raw-text
 * preview window), and LocalWebPreviewApp (the detached rendered-HTML
 * preview window) so the three surfaces share one implementation.
 *
 * `status: 'empty'` means the transport call succeeded but returned zero
 * versions for this path — the caller decides what that means (the sidebar
 * falls back to task-owned snapshots; the detached windows simply omit the
 * version controls). `status: 'error'` means the transport call itself
 * failed and is surfaced with a retry affordance; it is never treated as
 * "no version history" by any caller.
 */
export function useManagedVersionHistory({
  canonicalPath,
  enabled,
  rootTaskId,
  focusedAgentTaskId,
  refreshKey,
}: UseManagedVersionHistoryParams): UseManagedVersionHistoryResult {
  const [state, setState] = useState<ManagedVersionHistoryState>(EMPTY_STATE);
  const [reloadKey, setReloadKey] = useState(0);
  const requestEpoch = useRef(0);

  useEffect(() => {
    if (!enabled || !canonicalPath) {
      requestEpoch.current += 1;
      setState(EMPTY_STATE);
      return;
    }
    const requestId = requestEpoch.current + 1;
    requestEpoch.current = requestId;
    let isCurrent = true;
    setState({ ...EMPTY_STATE, status: 'loading' });

    async function load() {
      try {
        const versions = await listManagedFileVersions(canonicalPath!);
        if (!isCurrent || requestEpoch.current !== requestId) return;
        if (versions.length === 0) {
          setState({ ...EMPTY_STATE, status: 'empty' });
          return;
        }
        const matchedIndex = versions.findIndex(version => version.agentTaskId === focusedAgentTaskId);
        const selectedIndex = matchedIndex >= 0 ? matchedIndex : 0;
        const { selectedContent, compareContent } = await loadContentAt(versions, selectedIndex);
        if (!isCurrent || requestEpoch.current !== requestId) return;
        setState({
          ...EMPTY_STATE,
          status: 'ready',
          versions,
          selectedIndex,
          selectedContent,
          compareContent,
        });
      } catch (error) {
        if (!isCurrent || requestEpoch.current !== requestId) return;
        setState({
          ...EMPTY_STATE,
          status: 'error',
          errorMessage: error instanceof Error ? error.message : 'Unable to load version history for this document.',
        });
      }
    }

    void load();
    return () => {
      isCurrent = false;
    };
  }, [canonicalPath, enabled, focusedAgentTaskId, refreshKey, reloadKey]);

  const selectVersion = (index: number) => {
    if (state.restoreStatus === 'restoring' || index === state.selectedIndex || !state.versions[index]) {
      return;
    }
    const requestId = requestEpoch.current + 1;
    requestEpoch.current = requestId;
    setState(prev => ({ ...prev, status: 'loading', selectedIndex: index }));
    loadContentAt(state.versions, index)
      .then(({ selectedContent, compareContent }) => {
        if (requestEpoch.current !== requestId) return;
        setState(prev => ({ ...prev, status: 'ready', selectedIndex: index, selectedContent, compareContent }));
      })
      .catch(error => {
        if (requestEpoch.current !== requestId) return;
        setState(prev => ({
          ...prev,
          status: 'error',
          selectedIndex: index,
          errorMessage: error instanceof Error ? error.message : 'Unable to load this version of the document.',
        }));
      });
  };

  const restore = () => {
    if (!rootTaskId || !canonicalPath) return;
    const selected = state.versions[state.selectedIndex];
    if (!selected) return;
    const requestId = requestEpoch.current + 1;
    requestEpoch.current = requestId;
    setState(prev => ({ ...prev, restoreStatus: 'restoring', restoreErrorMessage: undefined }));
    restoreManagedFileVersion({
      rootTaskId,
      canonicalPath,
      restoresChangeId: selected.id,
      agentTaskId: focusedAgentTaskId,
    })
      .then(async result => {
        if (requestEpoch.current !== requestId) return;
        if (!result.success) {
          setState(prev => ({ ...prev, restoreStatus: 'error', restoreErrorMessage: result.error ?? 'Restore failed.' }));
          return;
        }
        const refreshedVersions = await listManagedFileVersions(canonicalPath);
        if (requestEpoch.current !== requestId) return;
        if (refreshedVersions.length === 0) {
          setState({ ...EMPTY_STATE, status: 'empty' });
          return;
        }
        const { selectedContent, compareContent } = await loadContentAt(refreshedVersions, 0);
        if (requestEpoch.current !== requestId) return;
        setState({
          ...EMPTY_STATE,
          status: 'ready',
          versions: refreshedVersions,
          selectedIndex: 0,
          selectedContent,
          compareContent,
        });
      })
      .catch(error => {
        if (requestEpoch.current !== requestId) return;
        setState(prev => ({
          ...prev,
          restoreStatus: 'error',
          restoreErrorMessage: error instanceof Error ? error.message : 'Restore failed unexpectedly.',
        }));
      });
  };

  const retry = () => setReloadKey(current => current + 1);

  return { state, canRestore: Boolean(rootTaskId), selectVersion, restore, retry };
}
