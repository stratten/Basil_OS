import type { RoutedNoticeState } from './HomeForwardContext';

interface RoutedNoticeProps {
  notice: RoutedNoticeState;
  onReroute: () => void;
  onDismiss: () => void;
  onEngagedChange: (engaged: boolean) => void;
}

export default function RoutedNotice({ notice, onReroute, onDismiss, onEngagedChange }: RoutedNoticeProps) {
  const toChat = notice.routeKind === 'conversation';
  const message = notice.rerouting
    ? 'Changing where this goes...'
    : toChat
      ? 'Sent to Chats as a conversation.'
      : 'Started as an agent task.';
  const correction = toChat ? 'Send as agent task instead' : 'Answer in a chat instead';

  return (
    <div
      className={`routed-notice${notice.error ? ' has-error' : ''}`}
      role="status"
      data-route-kind={notice.routeKind}
      onMouseEnter={() => onEngagedChange(true)}
      onMouseLeave={() => onEngagedChange(false)}
      onFocus={() => onEngagedChange(true)}
      onBlur={() => onEngagedChange(false)}
    >
      <span className="routed-notice-message">{message}</span>
      {notice.error ? <span className="routed-notice-error">{notice.error}</span> : null}
      <button type="button" className="routed-notice-action" onClick={onReroute} disabled={notice.rerouting}>
        {correction}
      </button>
      <button type="button" className="routed-notice-dismiss" onClick={onDismiss} aria-label="Dismiss">
        <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
          <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" />
        </svg>
      </button>
    </div>
  );
}
