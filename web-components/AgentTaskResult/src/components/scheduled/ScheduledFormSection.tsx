import { useId, type ReactNode } from 'react';

interface Props {
  title: string;
  children: ReactNode;
}

/** A titled group of rows in the scheduled-task form, so what the task is, what it can use, and when it runs read as three parts instead of one long list. */
export default function ScheduledFormSection({ title, children }: Props) {
  const headingId = useId();
  return (
    <section className="scheduled-section" aria-labelledby={headingId}>
      <h4 className="scheduled-section__heading" id={headingId}>{title}</h4>
      {children}
    </section>
  );
}
