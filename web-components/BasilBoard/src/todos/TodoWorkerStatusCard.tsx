import { useEffect, useState } from 'react';
import { openExistingAgentTaskWidget } from '../services/bridge';
import HomeMarkdown from '../home/HomeMarkdown';
import type { TodoWorkAttempt } from '../contracts';
import type { TodoWorkerLiveState } from './useTodoWorkerProgress';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import AgentTaskActiveIndicator from '@shared/AgentTaskActiveIndicator';
import NativeSymbolIcon from '../components/NativeSymbolIcon';
import { agentTaskIndicatorStatus } from './agentTaskIndicatorStatus';

interface TodoWorkerStatusCardProps {
  attempt: TodoWorkAttempt;
  liveState?: TodoWorkerLiveState;
}

const ATTENTION_STATUSES = new Set([
  'awaiting_user_input',
  'waiting_user_input',
  'needs_clarification',
]);

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'canceled']);
const RESULT_PREVIEW_EXPAND_THRESHOLD = 600;

type CardSeverity = 'success' | 'warning' | 'error' | 'canceled' | 'neutral';

function severityForStatus(
  status: string,
  liveState: TodoWorkerLiveState | undefined,
  attempt: TodoWorkAttempt,
): CardSeverity {
  if (status === 'canceled') return 'canceled';
  if (!TERMINAL_STATUSES.has(status)) return 'neutral';
  const resultSeverity = liveState?.detail?.result_severity ?? attempt.result_severity;
  if (resultSeverity === 'warning') return 'warning';
  if (resultSeverity === 'error') return 'error';
  if (resultSeverity === 'success') return 'success';
  return status === 'completed' ? 'success' : 'error';
}

function labelForSeverity(severity: CardSeverity): string {
  switch (severity) {
    case 'success': return 'Paprika task completed';
    case 'warning': return 'Partial result';
    case 'error': return 'Paprika task failed';
    case 'canceled': return 'Paprika task canceled';
    default: return 'Paprika task status unavailable';
  }
}

function labelForActiveStatus(status: string): string {
  switch (status) {
    case 'capturing': return 'Preparing Paprika task';
    case 'routing': return 'Planning Paprika task';
    case 'processing': return 'Paprika task in progress';
    case 'awaiting_provider_delegation': return 'Waiting for provider delegation';
    case 'awaiting_delegated_agents': return 'Waiting for delegated agents';
    case 'paused': return 'Paprika task paused';
    case 'awaiting_user_input':
    case 'waiting_user_input':
    case 'needs_clarification':
      return 'Paprika task needs your input';
    default: return 'Paprika task status unavailable';
  }
}

function iconForSeverity(severity: CardSeverity): string {
  switch (severity) {
    case 'success': return '✓';
    case 'warning': return '~';
    case 'error': return '!';
    case 'canceled': return '⨸';
    default: return '⋯';
  }
}

const WAITING_LABEL = 'Waiting to check again';

function formatNextCheck(value: string | null | undefined): string | undefined {
  if (!value) return undefined;
  const moment = new Date(value);
  if (Number.isNaN(moment.getTime())) return undefined;
  return moment.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

function resultMessage(liveState: TodoWorkerLiveState | undefined, attempt: TodoWorkAttempt): string | undefined {
  return liveState?.detail?.result_message
    ?? liveState?.detail?.error_message
    ?? attempt.result_summary
    ?? undefined;
}

export default function TodoWorkerStatusCard({ attempt, liveState }: TodoWorkerStatusCardProps) {
  const status = liveState?.detail?.status ?? attempt.status;
  const needsAttention = attempt.attention || ATTENTION_STATUSES.has(status);
  const activity = liveState?.latestActivity;
  const severity = severityForStatus(status, liveState, attempt);
  const isTerminal = TERMINAL_STATUSES.has(status);
  const indicatorStatus = isTerminal ? null : needsAttention ? 'awaitingInput' : agentTaskIndicatorStatus(status);
  const outcome = isTerminal ? resultMessage(liveState, attempt) : undefined;
  const title = plainMarkdownText(liveState?.detail?.title ?? attempt.title) || attempt.agent_task_id;
  const isWaiting = isTerminal && status !== 'canceled' && Boolean(attempt.next_follow_up_at);
  const nextCheck = isWaiting ? formatNextCheck(attempt.next_follow_up_at) : undefined;
  const statusClassSuffix = isWaiting ? 'waiting' : isTerminal ? severity : status;
  const label = needsAttention
    ? 'Paprika task needs your input'
    : isWaiting
      ? WAITING_LABEL
      : isTerminal ? labelForSeverity(severity) : labelForActiveStatus(status);
  const [isOutcomeExpanded, setIsOutcomeExpanded] = useState(false);
  const isOutcomeLong = (outcome?.length ?? 0) > RESULT_PREVIEW_EXPAND_THRESHOLD;

  useEffect(() => {
    setIsOutcomeExpanded(false);
  }, [outcome]);

  return (
    <article
      className={`todo-worker-status-card todo-worker-status-card--${statusClassSuffix}${needsAttention ? ' is-needs-attention' : ''}`}
      role={needsAttention ? 'alert' : 'status'}
      aria-label={label}
    >
      {indicatorStatus ? (
        <span className="todo-worker-status-card-indicator" aria-hidden="true">
          <AgentTaskActiveIndicator status={indicatorStatus} />
        </span>
      ) : (
        <span className="todo-worker-status-card-icon" aria-hidden="true">
          {isWaiting ? <NativeSymbolIcon name="refresh" size={12} /> : isTerminal ? iconForSeverity(severity) : '⋯'}
        </span>
      )}
      <div className="todo-worker-status-card-body">
        <span className="todo-worker-status-card-title">{title}</span>
        <span className="todo-worker-status-card-label">{label}</span>
        {activity && !isTerminal ? <span className="todo-worker-status-card-activity">{activity}</span> : null}
        {isWaiting ? (
          <span className="todo-worker-status-card-activity">
            {nextCheck ? `Paprika will check again automatically at ${nextCheck}.` : 'Paprika will check again automatically.'}
          </span>
        ) : null}
      </div>
      <button
        type="button"
        className="todo-worker-status-card-open"
        onClick={() => openExistingAgentTaskWidget(attempt.agent_task_id)}
      >
        {needsAttention ? 'Respond in Paprika' : 'Open in Paprika'}
      </button>
      {outcome ? (
        <div className="todo-worker-status-card-outcome-row">
          <div className={`todo-worker-status-card-outcome${isOutcomeLong && !isOutcomeExpanded ? ' is-truncated' : ''}`}>
            <HomeMarkdown content={outcome} variant="task" />
          </div>
          {isOutcomeLong ? (
            <button
              type="button"
              className="todo-worker-status-card-outcome-toggle"
              aria-expanded={isOutcomeExpanded}
              onClick={() => setIsOutcomeExpanded((expanded) => !expanded)}
            >
              {isOutcomeExpanded ? 'Show less' : 'Show full result'}
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
