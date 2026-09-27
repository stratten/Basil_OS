import { useEffect, useRef, useState } from 'react';
import type { ThinkingSegment } from '../../types';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import MarkdownRenderer from '../MarkdownRenderer';
import { shouldAutoCollapseThinking } from './thinkingPresentation';

export function ThinkingSegments({
  segments,
  isLive,
  collapseForResponse,
}: {
  segments: ThinkingSegment[];
  isLive: boolean;
  collapseForResponse: boolean;
}) {
  // A local model can loop through many reasoning iterations, each arriving
  // as its own ThinkingSegment. Rendering every one as its own standalone
  // pill dominates the main content area once there are more than a
  // handful. Only the latest segment (the one that can still be live) gets
  // its own standalone pill; every earlier segment collapses into a single
  // "N earlier reasoning steps" group, reusing the same ThinkingPill for
  // each item once expanded so nothing about an individual pill's own
  // rendering or per-item expand/collapse memory (keyed on seg.iteration)
  // changes. With one segment total -- the common case for tasks that
  // don't loop much -- there is no "earlier" group and this is identical
  // to before.
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
              defaultExpanded={segIsLive}
              label={undefined}
              collapseForResponse={collapseForResponse}
            />
          );
        })}
      </div>
    );
  }

  const earlierSegments = segments.slice(0, -1);
  const latestSegment = segments[segments.length - 1];
  const latestIsLive = isLive && !latestSegment.isComplete;

  return (
    <div className="thinking-segments">
      <ThinkingHistoryGroup segments={earlierSegments} />
      <ThinkingPill
        key={latestSegment.iteration}
        segment={latestSegment}
        isLive={latestIsLive}
        defaultExpanded={latestIsLive}
        label={`Reasoning (Step ${latestSegment.iteration})`}
        collapseForResponse={collapseForResponse}
      />
    </div>
  );
}

function ThinkingHistoryGroup({ segments }: { segments: ThinkingSegment[] }) {
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
            {segments.length} earlier reasoning step{segments.length === 1 ? '' : 's'}
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
                label={`Reasoning (Step ${seg.iteration})`}
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
}: {
  segment: ThinkingSegment;
  isLive: boolean;
  defaultExpanded: boolean;
  label?: string;
  collapseForResponse: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const previousLiveRef = useRef(isLive);
  const previousCollapseForResponseRef = useRef(collapseForResponse);
  const responseCollapseHandledRef = useRef(false);

  useEffect(() => {
    const wasLive = previousLiveRef.current;
    if (isLive && !wasLive) {
      setExpanded(true);
      responseCollapseHandledRef.current = false;
    }
    if (!isLive && wasLive) {
      setExpanded(false);
    }
    previousLiveRef.current = isLive;
  }, [isLive]);

  useEffect(() => {
    const wasStreaming = previousCollapseForResponseRef.current;
    if (wasStreaming && !collapseForResponse && isLive) {
      responseCollapseHandledRef.current = false;
    }
    if (shouldAutoCollapseThinking(wasStreaming, collapseForResponse, responseCollapseHandledRef.current)) {
      setExpanded(false);
      responseCollapseHandledRef.current = true;
    }
    previousCollapseForResponseRef.current = collapseForResponse;
  }, [collapseForResponse]);

  return (
    <div className="thinking-pill">
      <div className="execution-steps-header" onClick={() => setExpanded(!expanded)}>
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
  const previousLiveRef = useRef(isLive);
  const previousCollapseForResponseRef = useRef(collapseForResponse);
  const responseCollapseHandledRef = useRef(false);

  useEffect(() => {
    const wasLive = previousLiveRef.current;
    if (isLive && !wasLive) {
      setExpanded(true);
      responseCollapseHandledRef.current = false;
    }
    if (!isLive && wasLive) {
      setExpanded(false);
    }
    previousLiveRef.current = isLive;
  }, [isLive]);

  useEffect(() => {
    const wasStreaming = previousCollapseForResponseRef.current;
    if (wasStreaming && !collapseForResponse && isLive) {
      responseCollapseHandledRef.current = false;
    }
    if (shouldAutoCollapseThinking(wasStreaming, collapseForResponse, responseCollapseHandledRef.current)) {
      setExpanded(false);
      responseCollapseHandledRef.current = true;
    }
    previousCollapseForResponseRef.current = collapseForResponse;
  }, [collapseForResponse]);

  return (
    <div className="thinking-section">
      <div
        className="execution-steps-header"
        onClick={() => setExpanded(!expanded)}
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
