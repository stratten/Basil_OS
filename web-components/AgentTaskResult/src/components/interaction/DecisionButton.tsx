import type { ReactNode } from 'react';

export type DecisionTone = 'approve' | 'deny' | 'stop' | 'primary' | 'neutral';

interface DecisionButtonProps {
  tone: DecisionTone;
  /** One of the circle icons from the shared set. It is the only thing drawn, so the tooltip and the accessible name carry the meaning. */
  icon: ReactNode;
  /** The action's name. It is the accessible name and the start of the tooltip, and is hidden from view. */
  label: string;
  /** Absent on a submit button, which sends its form instead. */
  onClick?: () => void;
  /** Makes this the form's submit button. */
  submit?: boolean;
  disabled?: boolean;
  /** What the action does, shown after the label in the tooltip. */
  title?: string;
  /** Marks a toggle that is currently on, such as the work-review button while the question is docked. */
  pressed?: boolean;
  /** Pushes this button and everything before it to the left of the row, leaving the rest at the right. */
  lead?: boolean;
  className?: string;
}

/** The one button for every decision row on an approval or a question. It is a small icon-only button, the same size and shape as the Send button in the follow-up box and drawing a 17px icon, three pixels larger than the Stop and Pause icons, so the circle and glyph are easy to make out. The word stays in the page for screen readers, and the tooltip names the action. */
export function DecisionButton({ tone, icon, label, onClick, submit, disabled, title, pressed, lead, className }: DecisionButtonProps) {
  const classes = ['decision-btn', `decision-btn--${tone}`, lead ? 'decision-btn--lead' : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <button
      type={submit ? 'submit' : 'button'}
      className={classes}
      onClick={onClick}
      disabled={disabled}
      title={title ? `${label}: ${title}` : label}
      aria-pressed={pressed}
    >
      <span className="decision-btn__icon" aria-hidden="true">{icon}</span>
      <span className="decision-btn__label">{label}</span>
    </button>
  );
}

interface DecisionActionsProps {
  children: ReactNode;
  className?: string;
}

/** The row that holds decision buttons, packed to the right with a small gap. Every decision row follows one order. Tools that are not decisions come first and sit at the left, the work-review toggle before Stop. Decisions follow at the right, the negative one immediately before the positive one, so the way forward is always the right-most button. */
export function DecisionActions({ children, className }: DecisionActionsProps) {
  return <div className={`decision-actions${className ? ` ${className}` : ''}`}>{children}</div>;
}
