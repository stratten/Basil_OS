import type { CaptureSnapshot } from '../types';
import TaskAutoApproveToggle from '../../../shared/inputs/TaskAutoApproveToggle';
import { setTaskAutoApprove } from '../services/bridge';

interface Props {
  snapshot: CaptureSnapshot;
  /** For the narrow voice window, where only the switch fits. */
  compact?: boolean;
}

/** The capture window's auto-approve switch. It shows what native reports in the snapshot and only asks native to change it, because turning it on needs native's own confirmation dialog. */
export default function CaptureAutoApproveToggle({ snapshot, compact = false }: Props) {
  return (
    <TaskAutoApproveToggle
      enabled={snapshot.taskAutoApproveEnabled}
      pending={snapshot.taskAutoApprovePending}
      error={snapshot.taskAutoApproveError}
      disabled={snapshot.hasCompleted || snapshot.isSubmittingTextPrompt}
      compact={compact}
      onChange={setTaskAutoApprove}
    />
  );
}
