import type { BoardInquirySummary } from '../contracts';
import { plainMarkdownText } from '@shared/plainMarkdownText';

export const RECENT_REQUEST_LIMIT = 5;

interface RecentRequestsProps {
  inquiries: BoardInquirySummary[];
  loading: boolean;
  loadError?: string;
  onOpen: (inquiry: BoardInquirySummary) => void;
  onRetry: () => void;
}

export function inquiryDestinationAvailable(inquiry: BoardInquirySummary): boolean {
  if (inquiry.routeKind === 'conversation') return Boolean(inquiry.conversationId);
  if (inquiry.routeKind === 'agent_task') return Boolean(inquiry.agentTaskId) && inquiry.state !== 'failed';
  return false;
}

function stateNote(inquiry: BoardInquirySummary): string | undefined {
  if (inquiry.state === 'failed') return 'Did not start';
  if (inquiry.state === 'canceled') return 'Canceled';
  if (inquiry.routeKind === 'agent_task' && (inquiry.state === 'running' || inquiry.state === 'routing')) return 'Running';
  return undefined;
}

function RouteIcon({ routeKind }: { routeKind?: BoardInquirySummary['routeKind'] }) {
  const common = {
    width: 14,
    height: 14,
    viewBox: '0 0 16 16',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.3,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  return routeKind === 'agent_task' ? (
    <svg {...common}><rect x="3" y="2.5" width="10" height="11" rx="1.5" /><path d="M6 6.5h4M6 9h4M6 11.5h2.5" /></svg>
  ) : (
    <svg {...common}><path d="M2.5 3.5h11v7h-6L4.5 13v-2.5h-2z" /></svg>
  );
}

export default function RecentRequests({ inquiries, loading, loadError, onOpen, onRetry }: RecentRequestsProps) {
  if (loadError) {
    return (
      <div className="home-recent home-recent-message" role="status">
        <span>Recent requests could not be loaded.</span>
        <button type="button" className="home-recent-retry" onClick={onRetry}>Retry</button>
      </div>
    );
  }
  if (inquiries.length === 0) {
    return (
      <div className="home-recent home-recent-message" role="status">
        <span>{loading ? 'Loading recent requests...' : 'Nothing yet. Your recent requests will show up here.'}</span>
      </div>
    );
  }

  return (
    <nav className="home-recent" aria-label="Recent requests">
      <h2 className="home-recent-heading">Recent</h2>
      <ul className="home-recent-list">
        {inquiries.slice(0, RECENT_REQUEST_LIMIT).map((inquiry) => {
          const available = inquiryDestinationAvailable(inquiry);
          const note = stateNote(inquiry);
          const destination = inquiry.routeKind === 'agent_task' ? 'Agents' : 'Chats';
          return (
            <li key={inquiry.id}>
              <button
                type="button"
                className={`home-recent-link home-recent-${inquiry.routeKind ?? 'unrouted'}`}
                disabled={!available}
                onClick={() => onOpen(inquiry)}
                title={available ? `Open in ${destination}` : undefined}
              >
                <span className="home-recent-icon"><RouteIcon routeKind={inquiry.routeKind} /></span>
                <span className="home-recent-text">{plainMarkdownText(inquiry.promptText)}</span>
                {note ? <span className="home-recent-note">{note}</span> : null}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
