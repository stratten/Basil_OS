import { useEffect, useRef } from 'react';
import TokenizedSelect from '@shared/TokenizedSelect';
import { registerValidationManagedHistoryRestoreHandler } from '../../../services/bridge';
import type { ManagedVersionHistoryState } from './useManagedVersionHistory';
import { managedVersionLabel } from './managedVersionPresentation';
import type { AgentTaskRunFocusSummary } from '../../run/agentTaskRunFocus';

export interface ManagedVersionControlsProps {
  state: ManagedVersionHistoryState;
  canRestore: boolean;
  runs?: AgentTaskRunFocusSummary[];
  onSelect: (index: number) => void;
  onRestore: () => void;
}

/**
 * Version dropdown + conditional "Restore this version" button. Renders
 * nothing when there is no version history to show. Shared by
 * ArtifactReviewWorkspace, FilePreviewApp, and LocalWebPreviewApp — all
 * three already load `artifact-review-workspace.css` (via
 * `components.css`), so the `.artifact-review-version-*` /
 * `.artifact-review-restore` classes resolve in every consumer without new
 * CSS.
 */
export function ManagedVersionControls({ state, canRestore, runs, onSelect, onRestore }: ManagedVersionControlsProps) {
  const pendingValidationRestoreRequestId = useRef<string>();
  const dispatchedValidationRestoreRequestId = useRef<string>();

  useEffect(() => registerValidationManagedHistoryRestoreHandler((requestId) => {
    if (!canRestore || !state.versions[1] || state.restoreStatus === 'restoring') return;
    pendingValidationRestoreRequestId.current = requestId;
    dispatchedValidationRestoreRequestId.current = undefined;
    if (state.selectedIndex !== 1) onSelect(1);
  }), [canRestore, onSelect, state.restoreStatus, state.selectedIndex, state.versions]);

  useEffect(() => {
    const requestId = pendingValidationRestoreRequestId.current;
    if (
      !requestId
      || dispatchedValidationRestoreRequestId.current === requestId
      || state.status !== 'ready'
      || state.selectedIndex !== 1
      || state.restoreStatus !== 'idle'
    ) {
      return;
    }
    dispatchedValidationRestoreRequestId.current = requestId;
    onRestore();
  }, [onRestore, state.restoreStatus, state.selectedIndex, state.status]);

  if (state.versions.length === 0) return null;
  const isNonHead = state.selectedIndex !== 0;
  return (
    <div className="artifact-review-version-controls">
      <label className="artifact-review-version-select-label">
        Version
        <TokenizedSelect
          className="artifact-review-version-select"
          value={state.selectedIndex}
          disabled={state.restoreStatus === 'restoring'}
          ariaLabel="Version"
          onValueChange={onSelect}
          options={state.versions.map((version, index) => ({
            value: index,
            label: managedVersionLabel(state.versions, index, runs),
          }))}
        />
      </label>
      {isNonHead && canRestore && (
        <button
          type="button"
          className="artifact-review-restore"
          onClick={onRestore}
          disabled={state.restoreStatus === 'restoring'}
        >
          {state.restoreStatus === 'restoring' ? 'Restoring…' : 'Restore this version'}
        </button>
      )}
    </div>
  );
}

export interface ManagedVersionRestoreErrorProps {
  state: ManagedVersionHistoryState;
}

/** Renders the restore-conflict/error message; renders nothing otherwise. */
export function ManagedVersionRestoreError({ state }: ManagedVersionRestoreErrorProps) {
  if (state.restoreStatus !== 'error') return null;
  return (
    <p className="artifact-review-status artifact-review-restore-error" role="alert">
      {state.restoreErrorMessage}
    </p>
  );
}
