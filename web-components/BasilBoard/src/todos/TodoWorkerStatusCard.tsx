import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { marked } from 'marked';
import { openExistingAgentTaskWidget, openExternalUrl } from '../services/bridge';
import type { TodoWorkAttempt } from '../contracts';
import type { TodoWorkerLiveState } from './useTodoWorkerProgress';
import { plainMarkdownText } from '@shared/plainMarkdownText';

interface TodoWorkerStatusCardProps {
  attempt: TodoWorkAttempt;
  liveState?: TodoWorkerLiveState;
}

const ACTIVE_STATUSES = new Set([
  'capturing',
  'routing',
  'processing',
  'awaiting_provider_delegation',
  'awaiting_delegated_agents',
  'paused',
]);

const ATTENTION_STATUSES = new Set([
  'awaiting_user_input',
  'waiting_user_input',
  'needs_clarification',
]);

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'canceled']);
const RESULT_PREVIEW_EXPAND_THRESHOLD = 600;
const ALLOWED_MARKDOWN_TAGS = new Set([
  'P', 'H1', 'H2', 'H3', 'H4', 'UL', 'OL', 'LI', 'STRONG', 'B', 'EM', 'I', 'U', 'CODE', 'PRE', 'BLOCKQUOTE', 'BR', 'A',
]);

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
    case 'success': return 'Agent task completed';
    case 'warning': return 'Partial result';
    case 'error': return 'Agent task failed';
    case 'canceled': return 'Agent task canceled';
    default: return 'Agent task status unavailable';
  }
}

function labelForActiveStatus(status: string): string {
  switch (status) {
    case 'capturing': return 'Preparing agent task';
    case 'routing': return 'Planning agent task';
    case 'processing': return 'Agent task in progress';
    case 'awaiting_provider_delegation': return 'Waiting for provider delegation';
    case 'awaiting_delegated_agents': return 'Waiting for delegated agents';
    case 'awaiting_user_input':
    case 'waiting_user_input':
    case 'needs_clarification':
      return 'Agent task needs your input';
    default: return 'Agent task status unavailable';
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

function resultMessage(liveState: TodoWorkerLiveState | undefined, attempt: TodoWorkAttempt): string | undefined {
  return liveState?.detail?.result_message
    ?? liveState?.detail?.error_message
    ?? attempt.result_summary
    ?? undefined;
}

function sanitizeMarkdownHtml(html: string): string {
  const document = new DOMParser().parseFromString(html, 'text/html');
  for (const element of Array.from(document.body.querySelectorAll('*'))) {
    if (!ALLOWED_MARKDOWN_TAGS.has(element.tagName)) {
      element.replaceWith(...Array.from(element.childNodes));
      continue;
    }
    for (const attribute of Array.from(element.attributes)) {
      if (element.tagName !== 'A' || attribute.name !== 'href') {
        element.removeAttribute(attribute.name);
      }
    }
    if (element.tagName === 'A' && !/^(https?:|mailto:)/i.test(element.getAttribute('href') ?? '')) {
      element.removeAttribute('href');
    }
  }
  return document.body.innerHTML;
}

function renderResultMarkdown(content: string): string {
  const normalized = content.replace(/^[•●]\s/gm, '- ');
  try {
    return sanitizeMarkdownHtml(marked.parse(normalized, { breaks: true, gfm: true }) as string);
  } catch {
    return `<p>${normalized.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</p>`;
  }
}

export default function TodoWorkerStatusCard({ attempt, liveState }: TodoWorkerStatusCardProps) {
  const status = liveState?.detail?.status ?? attempt.status;
  const isActive = ACTIVE_STATUSES.has(status);
  const needsAttention = attempt.attention || ATTENTION_STATUSES.has(status);
  const activity = liveState?.latestActivity;
  const severity = severityForStatus(status, liveState, attempt);
  const isTerminal = TERMINAL_STATUSES.has(status);
  const outcome = isTerminal ? resultMessage(liveState, attempt) : undefined;
  const title = plainMarkdownText(liveState?.detail?.title ?? attempt.title) || attempt.agent_task_id;
  const statusClassSuffix = isTerminal ? severity : status;
  const label = needsAttention ? 'Agent task needs your input' : isTerminal ? labelForSeverity(severity) : labelForActiveStatus(status);
  const [isOutcomeExpanded, setIsOutcomeExpanded] = useState(false);
  const outcomeHtml = useMemo(() => outcome ? renderResultMarkdown(outcome) : '', [outcome]);
  const isOutcomeLong = (outcome?.length ?? 0) > RESULT_PREVIEW_EXPAND_THRESHOLD;

  useEffect(() => {
    setIsOutcomeExpanded(false);
  }, [outcome]);

  function handleOutcomeLinkClick(event: MouseEvent<HTMLDivElement>): void {
    const anchor = (event.target as HTMLElement).closest('a');
    const href = anchor?.getAttribute('href');
    if (!href || !/^(https?:|mailto:)/i.test(href)) return;
    event.preventDefault();
    openExternalUrl(href);
  }

  return (
    <article
      className={`todo-worker-status-card todo-worker-status-card--${statusClassSuffix}${needsAttention ? ' is-needs-attention' : ''}`}
      role={needsAttention ? 'alert' : 'status'}
      aria-label={label}
    >
      <span className={`todo-worker-status-card-icon${isActive ? ' is-spinning' : ''}`} aria-hidden="true">
        {isTerminal ? iconForSeverity(severity) : '⋯'}
      </span>
      <div className="todo-worker-status-card-body">
        <span className="todo-worker-status-card-title">{title}</span>
        <span className="todo-worker-status-card-label">{label}</span>
        {activity && !isTerminal ? <span className="todo-worker-status-card-activity">{activity}</span> : null}
      </div>
      <button
        type="button"
        className="todo-worker-status-card-open"
        onClick={() => openExistingAgentTaskWidget(attempt.agent_task_id)}
      >
        {needsAttention ? 'Respond in Agent Task' : 'Open Agent Task'}
      </button>
      {outcome ? (
        <div className="todo-worker-status-card-outcome-row">
          <div
            className={`todo-worker-status-card-outcome${isOutcomeLong && !isOutcomeExpanded ? ' is-truncated' : ''}`}
            dangerouslySetInnerHTML={{ __html: outcomeHtml }}
            onClick={handleOutcomeLinkClick}
          />
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
