import './task-auto-approve-toggle.css';

export const TASK_AUTO_APPROVE_LABEL = 'Auto-approve';

const EXPLANATION_OFF = 'Run every command on this task without asking you first. Blocked commands, connected tools, and actions that grant Basil access still ask.';
const EXPLANATION_ON = 'Every command on this task runs without asking. Click to turn this off.';

interface TaskAutoApproveToggleProps {
  enabled: boolean;
  /** A change is waiting on the user's confirmation or on the backend. */
  pending?: boolean;
  /** Why the last change did not happen. Shown as the control's tooltip and marks it with an error border. */
  error?: string | null;
  disabled?: boolean;
  /** For a row too narrow for the chip: only the switch is drawn, and the label stays as its accessible name. */
  compact?: boolean;
  onChange: (enabled: boolean) => void;
}

/** A per-task switch that lets every command on the task run without asking. Sits beside the model picker. Turning it on is confirmed natively by whoever handles `onChange`, so `enabled` follows what they report, not the click. */
export default function TaskAutoApproveToggle({ enabled, pending = false, error = null, disabled = false, compact = false, onChange }: TaskAutoApproveToggleProps) {
  const className = [
    'task-auto-approve-toggle',
    compact ? 'task-auto-approve-toggle--compact' : null,
    enabled ? 'is-on' : null,
    pending ? 'is-pending' : null,
    error ? 'has-error' : null,
  ].filter(Boolean).join(' ');
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-busy={pending}
      className={className}
      disabled={disabled || pending}
      title={error || (enabled ? EXPLANATION_ON : EXPLANATION_OFF)}
      onClick={() => onChange(!enabled)}
    >
      <span className="task-auto-approve-toggle__track" aria-hidden="true" />
      <span className="task-auto-approve-toggle__label">{TASK_AUTO_APPROVE_LABEL}</span>
    </button>
  );
}
