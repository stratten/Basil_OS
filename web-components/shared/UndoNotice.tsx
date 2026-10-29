import { useEffect, useRef } from 'react';

export const UNDO_NOTICE_DEFAULT_MS = 8000;

interface UndoNoticeProps {
  /** Changes with each new notice, so a second one restarts the countdown instead of inheriting the first one's. */
  noticeKey: string | number;
  message: string;
  actionLabel?: string;
  onAction: () => void;
  /** Called when the countdown ends or the close button is pressed. The owner then stops rendering the notice. */
  onExpire: () => void;
  durationMs?: number;
  className?: string;
}

/** A short-lived "did that by mistake?" strip: what just happened, an Undo button, and a close button. It removes itself after `durationMs` through `onExpire`. */
export default function UndoNotice({ noticeKey, message, actionLabel = 'Undo', onAction, onExpire, durationMs = UNDO_NOTICE_DEFAULT_MS, className }: UndoNoticeProps) {
  const expire = useRef(onExpire);
  expire.current = onExpire;

  useEffect(() => {
    const timer = setTimeout(() => expire.current(), durationMs);
    return () => clearTimeout(timer);
  }, [noticeKey, durationMs]);

  return (
    <div className={['basil-undo-notice', 'basil-presence-enter', className].filter(Boolean).join(' ')} role="status">
      <span className="basil-undo-notice__message">{message}</span>
      <button type="button" className="basil-undo-notice__action" onClick={onAction}>{actionLabel}</button>
      <button type="button" className="basil-undo-notice__close" aria-label="Close" onClick={onExpire}>×</button>
    </div>
  );
}
