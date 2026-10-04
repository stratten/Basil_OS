import type { BoardInquirySummary } from '../contracts';
import { plainMarkdownText } from '@shared/plainMarkdownText';

function formatTimestamp(value?: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function stateLabel(state: BoardInquirySummary['state']): string {
  switch (state) {
    case 'routing':
      return 'Queued';
    case 'running':
      return 'Running';
    case 'completed':
      return 'Completed';
    case 'failed':
      return 'Failed';
    default:
      return 'Canceled';
  }
}

interface InquiryHistoryProps {
  inquiries: BoardInquirySummary[];
  selectedInquiryId: string | undefined;
  onSelect: (inquiryId: string) => void;
}

export default function InquiryHistory({ inquiries, selectedInquiryId, onSelect }: InquiryHistoryProps) {
  if (inquiries.length === 0) {
    return (
      <div className="home-empty-state home-inquiry-history-empty">
        <p>No inquiries yet. Ask Basil something below.</p>
      </div>
    );
  }

  return (
    <ul className="home-inquiry-history">
      {inquiries.map((inquiry) => (
        <li key={inquiry.id}>
          <button
            type="button"
            className={`home-inquiry-history-item home-inquiry-history-${inquiry.state}${
              inquiry.id === selectedInquiryId ? ' is-active' : ''
            }`}
            onClick={() => onSelect(inquiry.id)}
          >
            <span className="home-inquiry-history-prompt">{plainMarkdownText(inquiry.promptText)}</span>
            <span className="home-inquiry-history-meta">
              {stateLabel(inquiry.state)} · {formatTimestamp(inquiry.updatedAt ?? inquiry.createdAt)}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
