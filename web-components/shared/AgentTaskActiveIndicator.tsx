import './agent-task-active-indicator.css';

export type AgentTaskActiveIndicatorStatus = 'processing' | 'awaitingInput' | 'paused';

interface AgentTaskActiveIndicatorProps {
  status: AgentTaskActiveIndicatorStatus;
}

/** The in-flight glyph the Agent Task sidebar row shows for a running, waiting, or paused task.
 * Shared so every surface that mirrors an Agent Task's live state (the sidebar, the To-Do list and
 * work-history card) renders the identical indicator. */
export default function AgentTaskActiveIndicator({ status }: AgentTaskActiveIndicatorProps) {
  if (status === 'awaitingInput') {
    return (
      <svg width="12" height="12" viewBox="0 0 16 16" fill="var(--warning-base)" aria-hidden="true">
        <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm-.5 4.75v4.5a.75.75 0 0 0 1.5 0v-4.5a.75.75 0 0 0-1.5 0zM8 12a1 1 0 1 0 0-2 1 1 0 0 0 0 2z" />
      </svg>
    );
  }
  if (status === 'paused') {
    return (
      <svg className="agent-task-active-indicator--paused" width="12" height="12" viewBox="0 0 16 16" fillRule="evenodd" aria-label="Paused">
        <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM6 4.75a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5A.75.75 0 0 0 6 4.75zm4 0a.75.75 0 0 0-.75.75v5a.75.75 0 0 0 1.5 0v-5a.75.75 0 0 0-.75-.75z" />
      </svg>
    );
  }
  return <div className="pulsing-dots" aria-hidden="true"><span /><span /><span /></div>;
}
