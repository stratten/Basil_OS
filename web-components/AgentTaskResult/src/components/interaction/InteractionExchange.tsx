import { useEffect, useMemo, type ReactNode } from 'react';
import type { ThinkingSegment } from '../../types';
import MarkdownRenderer from '../MarkdownRenderer';
import { ThinkingSegments, useReasoningFollowState } from '../result/ThinkingSections';
import { formatTimestampForDisplay, useDateDisplayStyle } from '../../app/dateDisplay';
import ResponseCountdown from './ResponseCountdown';
import {
  interactionAskerLabel,
  interactionAskerSpeaker,
  interactionResponseLabel,
  interactionResponseSpeaker,
  interactionTranscriptCountdown,
  isApprovalLikeInteraction,
  runControlTone,
  splitReasoningAroundInteractions,
  visibleInteractionResponse,
  type InteractionSpeaker,
  type RunControlTone,
  type UserInteraction,
} from './userInteractions';

export function SpeechBubbleGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4.5 5.5h15v10h-8l-4.5 3.5v-3.5h-2.5z" />
    </svg>
  );
}

export function PersonGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="9" r="3.2" />
      <path d="M5.5 19c.8-3.4 3.4-5 6.5-5s5.7 1.6 6.5 5" />
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
  if (interaction.kind === 'connection_token' && interaction.status === 'resolved') return 'negative';
  if (interaction.status === 'answered' || interaction.status === 'approved' || interaction.status === 'resolved') return 'answer';
  return 'neutral';
}

export function InteractionExchange({ interaction }: { interaction: UserInteraction }) {
  const dateDisplayStyle = useDateDisplayStyle();
  const askedTime = useMemo(
    () => formatTimestampForDisplay(interaction.askedAt, dateDisplayStyle),
    [interaction.askedAt, dateDisplayStyle],
  );
  const respondedTime = useMemo(
    () => (interaction.respondedAt ? formatTimestampForDisplay(interaction.respondedAt, dateDisplayStyle) : ''),
    [interaction.respondedAt, dateDisplayStyle],
  );
  const tone = responseTone(interaction);
  const responseText = visibleInteractionResponse(interaction);
  const countdown = interactionTranscriptCountdown(interaction);

  // While a pause is waiting, the run-control composer at the bottom is the only surface, so the transcript does not repeat it.
  if (interaction.kind === 'pause' && interaction.status === 'waiting') return null;

  const askerSpeaker = interactionAskerSpeaker(interaction);
  const responseSpeaker = interactionResponseSpeaker(interaction);

  return (
    <section
      className={`interaction-exchange is-${interaction.status}`}
      data-interaction-entry-id={interaction.entryId}
      aria-label={`${interactionAskerLabel(interaction)}. ${interactionResponseLabel(interaction)}`}
    >
      <InteractionTurn speaker={askerSpeaker} tone="neutral" label={interactionAskerLabel(interaction)} time={askedTime}>
        {isApprovalLikeInteraction(interaction) ? (
          <pre className="interaction-exchange-command">{interaction.prompt}</pre>
        ) : (
          <div className="interaction-exchange-prompt">
            <MarkdownRenderer content={interaction.prompt} />
          </div>
        )}
      </InteractionTurn>
      <InteractionTurn
        speaker={responseSpeaker}
        tone={tone}
        label={interactionResponseLabel(interaction)}
        time={respondedTime}
        waiting={tone === 'waiting'}
        controlTone={runControlTone(interaction)}
      >
        {responseText && (
          <div className="interaction-exchange-response-text">{responseText}</div>
        )}
        {countdown && <ResponseCountdown timeLimit={countdown} variant="inline" />}
      </InteractionTurn>
    </section>
  );
}

/** One side of an exchange: app turns sit on the left with the app glyph, user turns on the right with the person glyph. */
function InteractionTurn({
  speaker,
  tone,
  label,
  time,
  waiting = false,
  controlTone = null,
  children,
}: {
  speaker: InteractionSpeaker;
  tone: 'answer' | 'waiting' | 'negative' | 'neutral';
  label: string;
  time: string;
  waiting?: boolean;
  controlTone?: RunControlTone | null;
  children?: ReactNode;
}) {
  return (
    <div className={`interaction-turn is-${speaker} is-${tone}${controlTone && tone === 'waiting' ? ` is-run-control-${controlTone}` : ''}`} data-speaker={speaker}>
      <div className="interaction-turn-heading">
        <span className="interaction-turn-glyph">{speaker === 'user' ? <PersonGlyph /> : <SpeechBubbleGlyph />}</span>
        {waiting && <span className="interaction-exchange-waiting-dot" aria-hidden="true" />}
        <span className="interaction-turn-label">{label}</span>
        {time && <span className="interaction-exchange-time">{time}</span>}
      </div>
      {children}
    </div>
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
