import type { ReactNode } from 'react';

interface Props {
  label: string;
  /** Hover text explaining the row; shown on the label. */
  help?: string;
  /** Names the control the label belongs to, when it is one control. */
  htmlFor?: string;
  children: ReactNode;
}

/** One labeled row of the scheduled-task form. Every row uses the same label column, type size and spacing, so the form reads as one layout. */
export default function ScheduledField({ label, help, htmlFor, children }: Props) {
  return (
    <div className="scheduled-field">
      {htmlFor ? (
        <label className="scheduled-field__label" htmlFor={htmlFor} title={help}>
          {label}
        </label>
      ) : (
        <span className="scheduled-field__label" title={help}>
          {label}
        </span>
      )}
      <div className="scheduled-field__body">{children}</div>
    </div>
  );
}
