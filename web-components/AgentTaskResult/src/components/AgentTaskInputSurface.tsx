import type { ReactNode } from 'react';

interface Props {
  eyebrow: string;
  children: ReactNode;
  isReviewingOutput: boolean;
  /** One line describing what Basil is asking, shown on the docked card while the user looks over the work. */
  dockSummary?: string;
  /** Returns from the docked card to the full question. */
  onResumeQuestion?: () => void;
}

export default function AgentTaskInputSurface({
  eyebrow,
  children,
  isReviewingOutput,
  dockSummary,
  onResumeQuestion,
}: Props) {
  return (
    <div className={`agent-task-input-backdrop${isReviewingOutput ? ' agent-task-input-backdrop--reviewing-output' : ''}`}>
      <section
        className={`agent-task-input-dialog${isReviewingOutput ? ' agent-task-input-dialog--reviewing-output' : ''}`}
        role={isReviewingOutput ? 'region' : 'dialog'}
        aria-modal={isReviewingOutput ? undefined : true}
        aria-labelledby={isReviewingOutput ? 'agent-task-input-dock-eyebrow' : 'agent-task-input-eyebrow'}
        data-agent-desk-interactive-overlay="true"
        data-preferred-content-width={isReviewingOutput ? 720 : 520}
      >
        {isReviewingOutput && (
          <div className="agent-task-input-dock">
            <div className="agent-task-input-dock-text">
              <div id="agent-task-input-dock-eyebrow" className="agent-task-input-eyebrow agent-task-input-dock-eyebrow">
                {eyebrow}
              </div>
              {dockSummary && <div className="agent-task-input-dock-summary">{dockSummary}</div>}
            </div>
            <button type="button" className="action-btn primary agent-task-input-dock-action" onClick={onResumeQuestion}>
              Answer now
            </button>
          </div>
        )}
        {/* The full question stays mounted while docked so entered text, selections and scroll position survive the round trip. */}
        <div className="agent-task-input-full" hidden={isReviewingOutput}>
          <div id="agent-task-input-eyebrow" className="agent-task-input-eyebrow">
            {eyebrow}
          </div>
          <div className="agent-task-input-body">
            {children}
          </div>
        </div>
      </section>
    </div>
  );
}
