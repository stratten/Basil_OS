import { useEffect, useRef, useState } from 'react';
import type { ThinkingSegment } from '../../types';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import MarkdownRenderer from '../MarkdownRenderer';
import { shouldAutoCollapseThinking } from './thinkingPresentation';

/** Whether the newest reasoning pass is shown open. A new pass takes over the open view and the pass it replaces folds into the earlier passes. */
export interface ReasoningFollowState {
  open: boolean;
  setOpen: (open: boolean) => void;
}

/** Reasoning starts closed and only the user opens or closes the latest pass. While it is open, each new pass opens in its place, through the response and after the run ends. */
export function useReasoningFollowState(): ReasoningFollowState {
  const [open, setOpen] = useState(false);
  return { open, setOpen };
}

/** Negative iterations are the backend's post-loop passes: -1 writes the final answer, -2 verifies the outcome. */
export function reasoningPassLabel(iteration: number): string {
  if (iteration === -1) return 'Reasoning (Final answer)';
  if (iteration === -2) return 'Reasoning (Verifying the outcome)';
  return `Reasoning (Step ${iteration})`;
}

export function ThinkingSegments({
  segments,
  isLive,
  isRunActive,
  collapseForResponse,
  follow,
  followable = true,
}: {
  segments: ThinkingSegment[];
  isLive: boolean;
  isRunActive?: boolean;
  collapseForResponse: boolean;
  follow?: ReasoningFollowState;
  followable?: boolean;
}) {
  const ownFollow = useReasoningFollowState();
  const active = followable ? follow ?? ownFollow : undefined;
  const runActive = isRunActive ?? isLive;

  const followProps = active
    ? { followOpen: active.open, onUserToggle: active.setOpen }
    : {};

  // A local model can loop through many reasoning iterations, each arriving
  // as its own ThinkingSegment. Only the latest segment gets its own
  // standalone pill; every earlier segment collapses into a single
  // "N earlier reasoning passes" group. The latest pill's open state is
  // owned here rather than by the pill, so a new pass opens exactly as the
  // previous one was left. Once the run is no longer active and the user is
  // not holding the reasoning open, every step folds into one group.
  if (segments.length <= 1) {
    return (
      <div className="thinking-segments">
        {segments.map((seg) => {
          const segIsLive = isLive && !seg.isComplete;
          return (
            <ThinkingPill
              key={seg.iteration}
              segment={seg}
              isLive={segIsLive}
              defaultExpanded={false}
              label={seg.iteration < 0 ? reasoningPassLabel(seg.iteration) : undefined}
              collapseForResponse={collapseForResponse}
              {...followProps}
            />
          );
        })}
      </div>
    );
  }

  if (!runActive && !active?.open) {
    return (
      <div className="thinking-segments">
        <ThinkingHistoryGroup
          segments={segments}
          title={`${segments.length} reasoning passes`}
        />
      </div>
    );
  }

  const earlierSegments = segments.slice(0, -1);
  const latest = segments[segments.length - 1];
  const latestIsLive = isLive && !latest.isComplete;

  return (
    <div className="thinking-segments">
      <ThinkingHistoryGroup
        segments={earlierSegments}
        title={`${earlierSegments.length} earlier reasoning ${earlierSegments.length === 1 ? 'pass' : 'passes'}`}
      />
      <ThinkingPill
        key={latest.iteration}
        segment={latest}
        isLive={latestIsLive}
        defaultExpanded={false}
        label={reasoningPassLabel(latest.iteration)}
        collapseForResponse={collapseForResponse}
        {...followProps}
      />
    </div>
  );
}

function ThinkingHistoryGroup({ segments, title }: { segments: ThinkingSegment[]; title: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="thinking-history-group">
      <div className="execution-steps-header" onClick={() => setExpanded(!expanded)}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="8" cy="8" r="6" /><path d="M8 5v3l2 1" />
          </svg>
          <span style={{
            fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
            color: 'var(--text-tertiary)',
          }}>
            {title}
          </span>
        </div>
        <ExecutionDisclosureChevron expanded={expanded} />
      </div>
      <div className={`thinking-collapse ${expanded ? 'expanded' : ''}`}>
        <div className="thinking-collapse-inner">
          <div className="thinking-history-group-items">
            {segments.map((seg) => (
              <ThinkingPill
                key={seg.iteration}
                segment={seg}
                isLive={false}
                defaultExpanded={false}
                label={reasoningPassLabel(seg.iteration)}
                collapseForResponse={false}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function ThinkingPill({
  segment,
  isLive,
  defaultExpanded,
  label,
  collapseForResponse,
  followOpen,
  onUserToggle,
}: {
  segment: ThinkingSegment;
  isLive: boolean;
  defaultExpanded: boolean;
  label?: string;
  collapseForResponse: boolean;
  followOpen?: boolean;
  onUserToggle?: (open: boolean) => void;
}) {
  const isFollowed = followOpen !== undefined;
  const [localExpanded, setLocalExpanded] = useState(followOpen ?? defaultExpanded);
  const previousCollapseForResponseRef = useRef(collapseForResponse);
  const responseCollapseHandledRef = useRef(false);

  useEffect(() => {
    if (followOpen !== undefined) setLocalExpanded(followOpen);
  }, [followOpen]);

  useEffect(() => {
    const wasStreaming = previousCollapseForResponseRef.current;
    previousCollapseForResponseRef.current = collapseForResponse;
    if (isFollowed) return;
    if (wasStreaming && !collapseForResponse && isLive) {
      responseCollapseHandledRef.current = false;
    }
    if (shouldAutoCollapseThinking(wasStreaming, collapseForResponse, responseCollapseHandledRef.current)) {
      setLocalExpanded(false);
      responseCollapseHandledRef.current = true;
    }
  }, [collapseForResponse, isFollowed, isLive]);

  const expanded = followOpen ?? localExpanded;
  const toggle = () => {
    const next = !expanded;
    setLocalExpanded(next);
    onUserToggle?.(next);
  };

  return (
    <div className="thinking-pill">
      <div className="execution-steps-header" onClick={toggle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isLive ? (
            <span style={{
              display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
              background: 'var(--primary)', animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          ) : (
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="8" cy="8" r="6" /><path d="M8 5v3l2 1" />
            </svg>
          )}
          <span style={{
            fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
            color: isLive ? 'var(--text-primary)' : 'var(--text-tertiary)',
          }}>
            {label ?? (isLive ? 'Reasoning…' : 'Reasoning')}
          </span>
        </div>
        <ExecutionDisclosureChevron expanded={expanded} />
      </div>
      <div className={`thinking-collapse ${expanded ? 'expanded' : ''}`}>
        <div className="thinking-collapse-inner">
          <div className="execution-steps-body" style={{ maxHeight: 300, overflow: 'auto' }}>
            <div style={{
              fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-status-small)',
              color: 'var(--text-secondary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              margin: 0, userSelect: 'text', opacity: 0.85,
            }}>
              <MarkdownRenderer content={segment.text} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function ThinkingSection({
  thinking,
  isLive,
  defaultExpanded,
  collapseForResponse,
}: {
  thinking: string;
  isLive: boolean;
  defaultExpanded: boolean;
  collapseForResponse: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const pinnedRef = useRef(false);
  const previousCollapseForResponseRef = useRef(collapseForResponse);
  const responseCollapseHandledRef = useRef(false);

  useEffect(() => {
    const wasStreaming = previousCollapseForResponseRef.current;
    previousCollapseForResponseRef.current = collapseForResponse;
    if (pinnedRef.current) return;
    if (wasStreaming && !collapseForResponse && isLive) {
      responseCollapseHandledRef.current = false;
    }
    if (shouldAutoCollapseThinking(wasStreaming, collapseForResponse, responseCollapseHandledRef.current)) {
      setExpanded(false);
      responseCollapseHandledRef.current = true;
    }
  }, [collapseForResponse, isLive]);

  const toggle = () => {
    pinnedRef.current = true;
    setExpanded(!expanded);
  };

  return (
    <div className="thinking-section">
      <div
        className="execution-steps-header"
        onClick={toggle}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {isLive ? (
            <span style={{
              display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
              background: 'var(--primary)', animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          ) : (
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="8" cy="8" r="6" />
              <path d="M8 5v3l2 1" />
            </svg>
          )}
          <span style={{
            fontFamily: 'var(--font-family-medium)',
            fontSize: 'var(--font-size-status-small)',
            color: isLive ? 'var(--text-primary)' : 'var(--text-tertiary)',
          }}>
            {isLive ? 'Reasoning…' : 'Reasoning'}
          </span>
        </div>
        <ExecutionDisclosureChevron expanded={expanded} />
      </div>

      <div className={`thinking-collapse ${expanded ? 'expanded' : ''}`}>
        <div className="thinking-collapse-inner">
          <div className="execution-steps-body" style={{ maxHeight: 300, overflow: 'auto' }}>
            <div style={{
              fontFamily: 'var(--font-family-light)',
              fontSize: 'var(--font-size-status-small)',
              color: 'var(--text-secondary)',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              margin: 0,
              userSelect: 'text',
              opacity: 0.85,
            }}>
              <MarkdownRenderer content={thinking} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
