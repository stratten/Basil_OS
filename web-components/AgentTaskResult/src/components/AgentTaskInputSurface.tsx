import type { ReactNode } from 'react';

interface Props {
  eyebrow: string;
  children: ReactNode;
  isReviewingOutput: boolean;
}

export default function AgentTaskInputSurface({ eyebrow, children, isReviewingOutput }: Props) {
  return (
    <div className={`agent-task-input-backdrop${isReviewingOutput ? ' agent-task-input-backdrop--reviewing-output' : ''}`}>
      <section
        className={`agent-task-input-dialog${isReviewingOutput ? ' agent-task-input-dialog--reviewing-output' : ''}`}
        role={isReviewingOutput ? 'region' : 'dialog'}
        aria-modal={isReviewingOutput ? undefined : true}
        aria-labelledby="agent-task-input-eyebrow"
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={isReviewingOutput ? 720 : 520}
      >
        <div id="agent-task-input-eyebrow" className="agent-task-input-eyebrow">
          {eyebrow}
        </div>
        <div className="agent-task-input-body">
          {children}
        </div>
      </section>
    </div>
  );
}
