import type { AgentTaskPresentationSummary } from '../../artifacts/artifactContract';

export interface AgentTaskWorkSummaryProps {
  summary?: AgentTaskPresentationSummary;
  isProcessing: boolean;
  errorMessage?: string;
}

function workflowLabel(summary: AgentTaskPresentationSummary): string | undefined {
  const { completedSteps, totalSteps } = summary.workflow;
  return completedSteps === undefined || totalSteps === undefined ? undefined : `${completedSteps} of ${totalSteps} steps`;
}

export function AgentTaskWorkSummary({ summary, isProcessing, errorMessage }: AgentTaskWorkSummaryProps) {
  if (!summary) return null;
  const workflow = workflowLabel(summary);
  return (
    <section className="agent-task-work-summary" aria-labelledby="agent-task-work-summary-title">
      <div className="agent-task-work-summary-heading">
        <h2 id="agent-task-work-summary-title">Work summary</h2>
        {isProcessing && <span className="agent-task-work-summary-progress" role="status">Work in progress</span>}
      </div>
      <dl className="agent-task-work-summary-metrics">
        <div><dt>Lifecycle</dt><dd>{summary.lifecycle}</dd></div>
        {summary.latestActivity && <div><dt>Latest activity</dt><dd>{summary.latestActivity}</dd></div>}
        {workflow && <div><dt>Workflow</dt><dd>{workflow}</dd></div>}
        <div><dt>Artifacts</dt><dd>{summary.artifactCount}</dd></div>
        <div>
          <dt>Verification</dt>
          <dd className={`agent-task-work-summary-verification--${summary.verificationStatus}`}>
            {summary.verificationStatus}
          </dd>
        </div>
        <div><dt>Attention</dt><dd>{summary.requiresUserAttention ? 'Required' : 'Not required'}</dd></div>
      </dl>
      {errorMessage && <p className="agent-task-work-summary-error" role="status">Task reported an error</p>}
    </section>
  );
}
