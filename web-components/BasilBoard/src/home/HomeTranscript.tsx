import type { HomeTimelineItem } from '../contracts';
import { openExistingAgentTaskWidget } from '../services/bridge';
import HomeMarkdown from './HomeMarkdown';

interface HomeTranscriptProps {
  items: HomeTimelineItem[];
  emptyLabel?: string;
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function stateLabel(state: Extract<HomeTimelineItem, { kind: 'agent_task' }>['state']): string {
  switch (state) {
    case 'queued':
      return 'Queued';
    case 'running':
      return 'Running';
    case 'completed':
      return 'Completed';
    case 'failed':
      return 'Failed';
    default:
      return 'Cancelled';
  }
}

function stateIcon(state: Extract<HomeTimelineItem, { kind: 'agent_task' }>['state']) {
  if (state === 'completed') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" /><path d="M5.5 8.2l2 2 3.5-4" />
      </svg>
    );
  }
  if (state === 'failed' || state === 'cancelled') {
    return (
      <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <circle cx="8" cy="8" r="6.5" /><path d="M5.5 5.5l5 5M10.5 5.5l-5 5" />
      </svg>
    );
  }
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
      <circle cx="8" cy="8" r="6.5" /><path d="M8 4.5v4l2.5 1.5" />
    </svg>
  );
}

function AttachmentStrip({ paths }: { paths: string[] }) {
  const visible = paths.slice(0, 3);
  const overflow = paths.length - visible.length;

  return (
    <div className="home-attachment-strip" aria-label="Attached references">
      {visible.map((path) => (
        <span key={path} className="home-attachment-chip" title={path}>
          <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden="true">
            <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
          </svg>
          <span>{basename(path)}</span>
        </span>
      ))}
      {overflow > 0 ? (
        <span className="home-attachment-overflow" title={paths.slice(3).join('\n')}>
          +{overflow} more
        </span>
      ) : null}
    </div>
  );
}

function AgentTaskCard({ item }: { item: Extract<HomeTimelineItem, { kind: 'agent_task' }> }) {
  const liveStatus = item.state === 'queued' || item.state === 'running';
  const failureBody = item.result || (item.state === 'failed' ? 'Task failed.' : undefined);

  return (
    <article className={`home-agent-task-card home-agent-task-${item.state}`}>
      <div className="home-agent-task-header">
        <div className="home-agent-task-status">
          {stateIcon(item.state)}
          <span className="home-agent-task-state">{stateLabel(item.state)}</span>
          {liveStatus ? (
            <span className="home-agent-task-live" aria-live="polite">
              {item.state === 'queued' ? 'Waiting to start…' : 'Working on your request…'}
            </span>
          ) : null}
        </div>
        <button
          type="button"
          className="home-agent-task-open"
          onClick={() => openExistingAgentTaskWidget(item.agentTaskId)}
          aria-label="Open task"
          title="Open task"
        >
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
            <path d="M6 2.5H3.5A1.5 1.5 0 0 0 2 4v8.5A1.5 1.5 0 0 0 3.5 14H12a1.5 1.5 0 0 0 1.5-1.5V10" />
            <path d="M9 2h5v5" /><path d="M14 2L7 9" />
          </svg>
        </button>
      </div>
      {item.outcome ? <span className="home-agent-task-outcome">{item.outcome}</span> : null}
      {item.result && item.state === 'completed' ? (
        <HomeMarkdown content={item.result} variant="task" />
      ) : null}
      {failureBody && item.state === 'failed' ? (
        <div className="home-agent-task-error">
          <HomeMarkdown content={failureBody} variant="task" />
        </div>
      ) : null}
      {!item.result && liveStatus ? <p className="home-agent-task-running">Basil is executing this task.</p> : null}
    </article>
  );
}

export default function HomeTranscript({ items, emptyLabel = 'No conversation yet.' }: HomeTranscriptProps) {
  if (items.length === 0) {
    return (
      <div className="home-empty-state">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="1.5" aria-hidden="true">
          <path d="M12 3c4.4 0 8 2.7 8 6v4c0 3.3-3.6 6-8 6s-8-2.7-8-6V9c0-3.3 3.6-6 8-6z" />
          <path d="M8 14.5c1.2 1 2.7 1.5 4 1.5s2.8-.5 4-1.5" />
        </svg>
        <p>{emptyLabel}</p>
      </div>
    );
  }

  return (
    <div className="home-transcript">
      <div className="home-transcript-column">
        {items.map((item) => {
          if (item.kind === 'user_message') {
            const referencePaths = item.referencePaths ?? [];
            return (
              <div key={item.messageId} className="home-message home-message-user">
                <span className="home-message-label">You</span>
                <HomeMarkdown content={item.displayMarkdown ?? item.content} variant="user" />
                {referencePaths.length > 0 ? <AttachmentStrip paths={referencePaths} /> : null}
              </div>
            );
          }
          if (item.kind === 'conversation_answer') {
            return (
              <div key={item.messageId} className="home-message home-message-assistant">
                <span className="home-message-label">Basil</span>
                <HomeMarkdown content={item.content} variant="assistant" />
              </div>
            );
          }
          return <AgentTaskCard key={`${item.agentTaskId}-${item.messageId}`} item={item} />;
        })}
      </div>
    </div>
  );
}
