import { useEffect, useRef, useState } from 'react';
import type { ProgressStep, StepDetailEntry, TimelineEntry } from '../../types';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import { normalizeProgressStepText } from './progressStepText';
import { conciseExecutionStepText, selectActivityTrail } from './activityPresentation';
import {
  hasVisibleActivity,
  nextActivityDisclosure,
  readableActivityCount,
  selectFallbackActivityTrail,
  type ActivityDisclosure,
} from './activityDockPresentation';

export function ProgressStepsSection({
  steps,
  timeline,
  stepDetails,
  selectedDetailId,
  onSelectDetail,
  isProcessing,
  presentation = 'inline',
  hasUnreadLiveContent = false,
  onJumpToLatestContent,
}: {
  steps: ProgressStep[];
  timeline?: TimelineEntry[];
  stepDetails?: StepDetailEntry[];
  selectedDetailId?: string | null;
  onSelectDetail?: (detail: StepDetailEntry, isLatest: boolean) => void;
  isProcessing: boolean;
  presentation?: 'inline' | 'dock';
  hasUnreadLiveContent?: boolean;
  onJumpToLatestContent?: () => void;
}) {
  const [disclosure, setDisclosure] = useState<ActivityDisclosure>('collapsed');
  const fullDetailsExpanded = disclosure === 'full';
  const listRef = useRef<HTMLDivElement>(null);
  const userScrolledRef = useRef(false);

  const hasTimeline = timeline && timeline.length > 0;
  const timelineEntries = timeline ?? [];
  const entryCount = hasTimeline ? timelineEntries.length : steps.length;
  const activityTrail = selectActivityTrail(timelineEntries);
  const hasActivityTrail = activityTrail.length > 0;
  const hasFullDetails = entryCount > 0;
  const isLive = isProcessing && entryCount > 0;
  const details = stepDetails || [];
  const latestDetailId = details[details.length - 1]?.id;

  const readableActivityEntries = selectActivityTrail(timelineEntries, 0);
  const latestReadableActivity = readableActivityEntries[readableActivityEntries.length - 1];
  const readableCount = readableActivityCount(timelineEntries) || steps.length;
  const latestStep = steps[steps.length - 1];

  const findDetailForTimelineEntry = (entry: TimelineEntry): StepDetailEntry | undefined => {
    return details.find(detail =>
      detail.id === entry.id ||
      detail.correlation_id === entry.id ||
      (entry.step_id && detail.step_id === entry.step_id) ||
      detail.summary === entry.content ||
      detail.content === entry.content
    );
  };

  const findDetailForStep = (step: ProgressStep): StepDetailEntry | undefined => {
    return details.find(detail =>
      (step.id && (detail.step_id === step.id || detail.correlation_id === step.id)) ||
      detail.summary === step.step ||
      detail.content === step.step
    );
  };

  useEffect(() => {
    const el = listRef.current;
    if (!el || !fullDetailsExpanded || userScrolledRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [entryCount, fullDetailsExpanded, isProcessing]);

  useEffect(() => {
    if (isProcessing) {
      userScrolledRef.current = false;
    }
  }, [isProcessing]);

  const handleScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30;
    userScrolledRef.current = !atBottom;
  };

  const fullCount = hasTimeline ? timelineEntries.length : steps.length;
  const showFullList = fullDetailsExpanded && hasFullDetails;
  const visibleTimelineEntries = showFullList ? timelineEntries : activityTrail;

  const renderTimelineRows = (entries: TimelineEntry[]) => entries.map((entry, i) => (
    <TimelineEntryRow
      key={entry.id || `activity-${i}`}
      entry={entry}
      detail={findDetailForTimelineEntry(entry)}
      isSelected={!!findDetailForTimelineEntry(entry) && selectedDetailId === findDetailForTimelineEntry(entry)?.id}
      onSelect={(detail) => onSelectDetail?.(detail, detail.id === latestDetailId)}
    />
  ));

  const renderStepRows = (visibleSteps = steps) => visibleSteps.map((step, i) => (
    <StepRow
      key={step.id || i}
      step={step}
      detail={findDetailForStep(step)}
      isSelected={!!findDetailForStep(step) && selectedDetailId === findDetailForStep(step)?.id}
      onSelect={(detail) => onSelectDetail?.(detail, detail.id === latestDetailId)}
    />
  ));

  const latestActivityLabel = latestReadableActivity
    ? conciseExecutionStepText(
      latestReadableActivity.content,
      findDetailForTimelineEntry(latestReadableActivity),
    )
    : latestStep
      ? conciseExecutionStepText(normalizeProgressStepText(latestStep.step), findDetailForStep(latestStep))
      : '';

  if (presentation === 'dock') {
    if (!hasVisibleActivity(timelineEntries, steps)) {
      return null;
    }

    const dockBodyOpen = disclosure !== 'collapsed';
    const dockVisibleEntries = disclosure === 'full' ? timelineEntries : activityTrail;

    return (
      <section className="execution-activity-dock">
        <button
          type="button"
          className="execution-activity-dock-header"
          aria-expanded={dockBodyOpen}
          onClick={() => setDisclosure(current => nextActivityDisclosure(current, 'toggleTrail'))}
        >
          <span className="execution-activity-dock-beacon-slot">
            {isLive ? <span className="execution-live-beacon" aria-hidden="true" /> : null}
          </span>
          <span className="execution-activity-dock-count">Activity · {readableCount} {readableCount === 1 ? 'step' : 'steps'}</span>
          {latestActivityLabel ? (
            <span className="execution-activity-dock-latest">{latestActivityLabel}</span>
          ) : null}
          <ExecutionDisclosureChevron expanded={dockBodyOpen} />
        </button>

        {hasUnreadLiveContent && onJumpToLatestContent ? (
          <button
            type="button"
            className="execution-activity-dock-jump"
            onClick={onJumpToLatestContent}
          >
            Jump to latest
          </button>
        ) : null}

        <div className={`execution-activity-dock-body${dockBodyOpen ? ' is-open' : ''}`}>
          <div className="execution-activity-dock-body-inner">
            {dockBodyOpen && hasTimeline && hasActivityTrail ? (
              <div
                ref={disclosure === 'full' ? listRef : undefined}
                onScroll={disclosure === 'full' ? handleScroll : undefined}
                className="execution-activity-dock-list"
                style={disclosure === 'full' ? { maxHeight: 250, overflow: 'auto' } : undefined}
              >
                {renderTimelineRows(dockVisibleEntries)}
              </div>
            ) : null}

            {dockBodyOpen && !hasActivityTrail && steps.length > 0 ? (
              <div
                ref={disclosure === 'full' ? listRef : undefined}
                onScroll={disclosure === 'full' ? handleScroll : undefined}
                className="execution-activity-dock-list"
                style={disclosure === 'full' ? { maxHeight: 250, overflow: 'auto' } : undefined}
              >
                {renderStepRows(
                  disclosure === 'full'
                    ? steps
                    : selectFallbackActivityTrail(steps),
                )}
              </div>
            ) : null}

            {dockBodyOpen && disclosure === 'trail' && hasFullDetails ? (
              <button
                type="button"
                className="execution-step-row activity-fulldetails-toggle execution-activity-dock-control"
                onClick={() => setDisclosure(current => nextActivityDisclosure(current, 'showFull'))}
              >
                <span className="execution-step-text" style={{
                  fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
                  color: 'var(--text-tertiary)',
                }}>
                  {`Full Details (${fullCount})`}
                </span>
                <ExecutionDisclosureChevron expanded={false} />
              </button>
            ) : null}

            {dockBodyOpen && disclosure === 'full' ? (
              <div className="execution-activity-dock-controls">
                <button
                  type="button"
                  className="execution-step-row activity-fulldetails-toggle execution-activity-dock-control"
                  onClick={() => setDisclosure(current => nextActivityDisclosure(current, 'showLess'))}
                >
                  <span className="execution-step-text" style={{
                    fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
                    color: 'var(--text-tertiary)',
                  }}>
                    Show less
                  </span>
                  <ExecutionDisclosureChevron expanded={false} />
                </button>
                <button
                  type="button"
                  className="execution-activity-dock-control execution-activity-dock-collapse"
                  onClick={() => setDisclosure(current => nextActivityDisclosure(current, 'collapse'))}
                >
                  Collapse activity
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </section>
    );
  }

  return (
    <div style={{ padding: '0 var(--padding-xs)', marginBottom: 'var(--padding-m)' }}>
      {(hasActivityTrail || hasFullDetails) && (
        <section className="activity-summary">
          <button
            type="button"
            className="activity-summary-header"
            aria-expanded={disclosure !== 'collapsed'}
            onClick={() => setDisclosure(current => nextActivityDisclosure(current, 'toggleTrail'))}
          >
            {isLive ? <span className="execution-live-beacon" aria-hidden="true" /> : null}
            <span className="activity-summary-header-count">Activity · {readableCount} {readableCount === 1 ? 'step' : 'steps'}</span>
            {disclosure === 'collapsed' && latestActivityLabel ? (
              <span className="activity-summary-header-latest">{latestActivityLabel}</span>
            ) : null}
            <ExecutionDisclosureChevron expanded={disclosure !== 'collapsed'} />
          </button>

          {disclosure !== 'collapsed' && (
            <div
              ref={listRef}
              onScroll={handleScroll}
              className="activity-summary-list"
              style={showFullList ? { maxHeight: 250, overflow: 'auto' } : undefined}
            >
              {hasActivityTrail
                ? renderTimelineRows(visibleTimelineEntries)
                : renderStepRows(showFullList ? steps : selectFallbackActivityTrail(steps))}
              {hasFullDetails && (
                <button
                  type="button"
                  className="execution-step-row activity-fulldetails-toggle"
                  onClick={() => setDisclosure(current =>
                    nextActivityDisclosure(current, fullDetailsExpanded ? 'showLess' : 'showFull')
                  )}
                >
                  <span className="execution-step-text" style={{
                    fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
                    color: 'var(--text-tertiary)',
                  }}>
                    {fullDetailsExpanded ? 'Show less' : `Full Details (${fullCount})`}
                  </span>
                  <ExecutionDisclosureChevron expanded={fullDetailsExpanded} />
                </button>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function TimelineEntryRow({
  entry,
  detail,
  isSelected,
  onSelect,
}: {
  entry: TimelineEntry;
  detail?: StepDetailEntry;
  isSelected?: boolean;
  onSelect?: (detail: StepDetailEntry) => void;
}) {
  const isThinking = entry.type === 'thinking';
  const isComplete = entry.type === 'tool_complete' || entry.type === 'step';
  const normalizedContent = normalizeProgressStepText(entry.content);
  const displayContent = conciseExecutionStepText(entry.content, detail);

  if (isThinking) {
    const preview = normalizedContent.length > 120
      ? normalizedContent.slice(0, 120) + '…'
      : normalizedContent;
    return (
      <button
        type="button"
        className={`execution-step-row ${detail ? 'has-detail' : ''} ${isSelected ? 'selected' : ''}`}
        onClick={() => detail && onSelect?.(detail)}
        disabled={!detail}
      >
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--secondary)" strokeWidth="1.3" style={{ flexShrink: 0, marginTop: 1 }}>
          <circle cx="8" cy="8" r="6" />
          <circle cx="8" cy="8" r="2" fill="var(--secondary)" />
        </svg>
        <span className="execution-step-text" style={{
          fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-status-small)',
          color: 'var(--text-secondary)', fontStyle: 'italic',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'text',
        }}>
          {preview}
        </span>
        <DetailDisclosureIcon visible={!!detail} />
      </button>
    );
  }

  return (
    <button
      type="button"
      className={`execution-step-row ${detail ? 'has-detail' : ''} ${isSelected ? 'selected' : ''}`}
      onClick={() => detail && onSelect?.(detail)}
      disabled={!detail}
    >
      {isComplete ? (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="var(--success-base)" style={{ flexShrink: 0, marginTop: 1 }}>
          <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm3.41 5.09a.75.75 0 0 0-1.06-.04L7.2 8.04 5.64 6.59a.75.75 0 1 0-1.02 1.1l2.1 1.95a.75.75 0 0 0 1.04-.03l3.65-3.46a.75.75 0 0 0-.04-1.06z"/>
        </svg>
      ) : (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" style={{ flexShrink: 0, marginTop: 1 }}>
          <circle cx="8" cy="8" r="6" />
        </svg>
      )}
      <span className="execution-step-text" style={{
        fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-status-small)',
        color: isComplete ? 'var(--text-secondary)' : 'var(--text-primary)',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'text',
      }}>
        {displayContent}
      </span>
      <DetailDisclosureIcon visible={!!detail} />
    </button>
  );
}

function DetailDisclosureIcon({ visible }: { visible: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        width: 12,
        height: 12,
        flexShrink: 0,
        marginTop: 1,
        opacity: visible ? 0.75 : 0,
        color: 'var(--text-secondary)',
        transition: 'opacity 0.15s',
      }}
    >
      {visible && (
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M6 4l4 4-4 4" />
        </svg>
      )}
    </span>
  );
}

function StepRow({
  step,
  detail,
  isSelected,
  onSelect,
}: {
  step: ProgressStep;
  detail?: StepDetailEntry;
  isSelected?: boolean;
  onSelect?: (detail: StepDetailEntry) => void;
}) {
  const normalizedStepText = normalizeProgressStepText(step.step);

  return (
    <button
      type="button"
      className={`execution-step-row ${detail ? 'has-detail' : ''} ${isSelected ? 'selected' : ''}`}
      onClick={() => detail && onSelect?.(detail)}
      disabled={!detail}
    >
      {step.isComplete ? (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="var(--success-base)" style={{ flexShrink: 0, marginTop: 1 }}>
          <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm3.41 5.09a.75.75 0 0 0-1.06-.04L7.2 8.04 5.64 6.59a.75.75 0 1 0-1.02 1.1l2.1 1.95a.75.75 0 0 0 1.04-.03l3.65-3.46a.75.75 0 0 0-.04-1.06z"/>
        </svg>
      ) : step.isActive ? (
        <span style={{ display: 'inline-block', width: 11, height: 11, flexShrink: 0, marginTop: 1 }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--processing-base)" strokeWidth="1.5" strokeDasharray="3 2">
            <circle cx="8" cy="8" r="6" />
          </svg>
        </span>
      ) : (
        <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" style={{ flexShrink: 0, marginTop: 1, opacity: 0.5 }}>
          <circle cx="8" cy="8" r="6" />
        </svg>
      )}
      <span className="execution-step-text" style={{
        fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-status-small)',
        color: step.isActive ? 'var(--text-primary)' : step.isComplete ? 'var(--text-secondary)' : 'var(--text-tertiary)',
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'text',
      }}>
        {conciseExecutionStepText(normalizedStepText, detail)}
      </span>
      <DetailDisclosureIcon visible={!!detail} />
    </button>
  );
}
