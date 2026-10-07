import { useEffect, useMemo } from 'react';
import type { ThinkingSegment } from '../../types';
import MarkdownRenderer from '../MarkdownRenderer';
import { ThinkingSegments, useReasoningFollowState } from '../result/ThinkingSections';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';
import {
  interactionAskerLabel,
  interactionResponseLabel,
  isApprovalLikeInteraction,
  splitReasoningAroundInteractions,
  visibleInteractionResponse,
  type UserInteraction,
} from './userInteractions';

export function SpeechBubbleGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 5.5h15v10h-8l-4.5 3.5v-3.5h-2.5z" />
    </svg>
  );
}

export function PausedGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 6.5v11M15 6.5v11" />
    </svg>
  );
}

export function YourTurnGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9.2 9.2a2.9 2.9 0 1 1 4.1 2.6c-.8.4-1.3 1.1-1.3 2v.7M12 17.6v.1" />
    </svg>
  );
}

function responseTone(interaction: UserInteraction): 'answer' | 'waiting' | 'negative' | 'neutral' {
  if (interaction.status === 'waiting') return 'waiting';
  if (interaction.status === 'denied' || interaction.status === 'timed_out' || interaction.status === 'canceled') return 'negative';
  if (interaction.status === 'answered' || interaction.status === 'approved' || interaction.status === 'resolved') return 'answer';
  return 'neutral';
}

export function InteractionExchange({ interaction }: { interaction: UserInteraction }) {
  const dateDisplayStyle = useDateDisplayStyle();
  const askedTime = useMemo(
    () => formatHistoryTimestamp(interaction.askedAt, dateDisplayStyle),
    [interaction.askedAt, dateDisplayStyle],
  );
  const respondedTime = useMemo(
    () => (interaction.respondedAt ? formatHistoryTimestamp(interaction.respondedAt, dateDisplayStyle) : ''),
    [interaction.respondedAt, dateDisplayStyle],
  );
  const tone = responseTone(interaction);
  const responseText = visibleInteractionResponse(interaction);

  // While a pause is waiting, the run-control composer at the bottom is the only surface, so the transcript does not repeat it.
  if (interaction.kind === 'pause' && interaction.status === 'waiting') return null;

  return (
    <section
      className={`interaction-exchange is-${interaction.status}`}
      data-interaction-entry-id={interaction.entryId}
      aria-label={`${interactionAskerLabel(interaction)}. ${interactionResponseLabel(interaction)}`}
    >
      <div className="interaction-exchange-ask">
        <div className="interaction-exchange-heading">
          <span className="interaction-exchange-glyph"><SpeechBubbleGlyph /></span>
          <span className="interaction-exchange-asker">{interactionAskerLabel(interaction)}</span>
          {askedTime && <span className="interaction-exchange-time">{askedTime}</span>}
        </div>
        {isApprovalLikeInteraction(interaction) ? (
          <pre className="interaction-exchange-command">{interaction.prompt}</pre>
        ) : (
          <div className="interaction-exchange-prompt">
            <MarkdownRenderer content={interaction.prompt} />
          </div>
        )}
      </div>
      <div className={`interaction-exchange-response is-${tone}`}>
        <div className="interaction-exchange-response-heading">
          {tone === 'waiting' && <span className="interaction-exchange-waiting-dot" aria-hidden="true" />}
          <span>{interactionResponseLabel(interaction)}</span>
          {respondedTime && <span className="interaction-exchange-time">{respondedTime}</span>}
        </div>
        {responseText && (
          <div className="interaction-exchange-response-text">{responseText}</div>
        )}
      </div>
    </section>
  );
}

/** Reasoning passes with any exchanges with the user placed between the passes they interrupted. */
export function ReasoningWithInteractions({
  segments,
  interactions,
  isLive,
  isRunActive,
  collapseForResponse,
  runComplete = false,
}: {
  segments: ThinkingSegment[];
  interactions: UserInteraction[];
  isLive: boolean;
  isRunActive?: boolean;
  collapseForResponse: boolean;
  runComplete?: boolean;
}) {
  const blocks = useMemo(
    () => splitReasoningAroundInteractions(segments, interactions),
    [segments, interactions],
  );
  const follow = useReasoningFollowState();
  const { setOpen: setFollowOpen } = follow;
  useEffect(() => {
    if (runComplete) setFollowOpen(false);
  }, [runComplete, setFollowOpen]);
  if (interactions.length === 0) {
    return (
      <ThinkingSegments
        segments={segments}
        isLive={isLive}
        isRunActive={isRunActive}
        collapseForResponse={collapseForResponse}
        follow={follow}
      />
    );
  }

  const lastReasoningIndex = blocks.reduce((latest, block, index) => (block.type === 'reasoning' ? index : latest), -1);
  const liveTailIsReasoning = lastReasoningIndex === blocks.length - 1;
  return (
    <div className="reasoning-with-interactions">
      {blocks.map((block, index) => {
        if (block.type === 'interaction') {
          return <InteractionExchange key={block.key} interaction={block.interaction} />;
        }
        const isLastReasoning = index === lastReasoningIndex;
        const isTail = isLastReasoning && liveTailIsReasoning;
        return (
          <ThinkingSegments
            key={block.key}
            segments={block.segments}
            isLive={isTail && isLive}
            isRunActive={isTail ? isRunActive : false}
            collapseForResponse={isTail && collapseForResponse}
            follow={follow}
            followable={isLastReasoning}
          />
        );
      })}
    </div>
  );
}
