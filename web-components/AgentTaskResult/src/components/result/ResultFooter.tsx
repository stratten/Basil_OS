import { useMemo } from 'react';
import { formatTimestampForDisplay, useDateDisplayStyle } from '../../app/dateDisplay';
import { ModelUsedLabel } from './ModelUsedLabel';

interface ResultFooterProps {
  /** ISO timestamp the result was delivered; omitted when the run recorded none. */
  timestamp?: string;
  /** The model that answered; omitted when none was recorded. */
  modelId?: string;
  /** The local model that answered after the preferred model was unreachable, when that happened. */
  reasoningFallbackModelUsed?: string;
}

/** A quiet row below the final output: when the result was delivered, then which model answered. Renders nothing when there is nothing to say. */
export function ResultFooter({ timestamp, modelId, reasoningFallbackModelUsed }: ResultFooterProps) {
  const dateDisplayStyle = useDateDisplayStyle();
  const timeText = useMemo(
    () => (timestamp ? formatTimestampForDisplay(timestamp, dateDisplayStyle) : ''),
    [timestamp, dateDisplayStyle],
  );
  if (!timeText && !modelId && !reasoningFallbackModelUsed) return null;
  return (
    <div className="result-footer" data-run-section="result-footer">
      {timeText && (
        <time className="result-footer__time" dateTime={timestamp}>
          {timeText}
        </time>
      )}
      <ModelUsedLabel className="result-footer__model" modelId={modelId} prefix={timeText ? '·' : undefined} />
      {reasoningFallbackModelUsed && (
        <span
          className="result-footer__fallback"
          title={`Preferred model was unreachable before any response; answered by local fallback: ${reasoningFallbackModelUsed}`}
        >
          Answered with local fallback
        </span>
      )}
    </div>
  );
}
