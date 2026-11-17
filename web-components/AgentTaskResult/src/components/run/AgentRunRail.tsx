import { Fragment, useEffect, useReducer, useRef, type CSSProperties } from 'react';
import type { AgentRunOverviewPresentation } from './agentRunPresentation';
import { foldRailStages, isQuietRailStage, isRailFold, MIN_RAIL_FOLD, railFoldTitle, type RailStage } from './railFold';
import { PausedGlyph, SpeechBubbleGlyph, YourTurnGlyph } from '../interaction/InteractionExchange';
import { interactionSummary, runControlStageClass, runControlTone } from '../interaction/userInteractions';
import { isRevisionNumber, type AgentTaskRunFocusSummary } from './agentTaskRunFocus';
import { presentRunStatus, RUN_STATUS_TONE_CLASS } from './agentRunMapPresentation';
import { scrollVerticallyIntoView } from '../scrollVerticallyIntoView';
import ChecklistRailPill from '../checklist/ChecklistRailPill';
import ScheduledCheckGlyph from './ScheduledCheckGlyph';

function RailGlyph({ stage }: { stage: AgentRunOverviewPresentation['stages'][number] }) {
  if (stage.kind === 'interaction') {
    if (stage.interaction?.kind === 'pause' || stage.interaction?.kind === 'connection_lost') return <PausedGlyph />;
    return stage.state === 'waiting' && !runControlTone(stage.interaction) ? <YourTurnGlyph /> : <SpeechBubbleGlyph />;
  }
  if (stage.state === 'failed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>;
  }
  if (stage.artifactCount > 0) {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg>;
  }
  if (stage.state === 'completed') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4.2 4.2L19 7.5" /></svg>;
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="7" /><path d="M12 8v4l2.5 2.5" /></svg>;
}

function railStageTitle(stage: AgentRunOverviewPresentation['stages'][number]): string {
  if (stage.kind === 'interaction' && stage.interaction) {
    const summary = interactionSummary(stage.interaction);
    return stage.state === 'waiting' && !runControlTone(stage.interaction) ? `Your turn: ${summary}` : summary;
  }
  const state = stage.state === 'completed'
    ? 'completed'
    : stage.state === 'failed'
      ? 'needs attention'
      : stage.state === 'active'
        ? 'in progress'
        : stage.state;
  const documents = stage.artifactCount > 0
    ? `, ${stage.artifactCount} document${stage.artifactCount === 1 ? '' : 's'}`
    : '';
  return `${stage.label}: ${state}${documents}`;
}

interface AgentRunRailProps {
  overview: AgentRunOverviewPresentation;
  artifactCount?: number;
  runId?: string;
  isProcessing?: boolean;
  onExpand: () => void;
  runs?: AgentTaskRunFocusSummary[];
  locationRunId?: string;
  onNavigateRun?: (runId: string) => void;
  /** The chain whose checklist counter sits above the first turn. Omitted, the rail shows no checklist. */
  checklistRootId?: string;
}

/** Each chip arrives this much after the one above it. */
const ENTER_STAGGER_MS = 50;
/** The stagger stops growing here, so the last chip of a run with dozens of exchanges arrives about as soon as the first few do, instead of seconds later. */
const ENTER_STAGGER_CAP_MS = 600;
/** How close to the end of the rail counts as "following the run", in pixels. A reader who scrolled further up is left where they are when a new chip arrives. */
const FOLLOW_END_SLACK_PX = 40;

/** The flow's top and bottom padding in agent-run-rail.css, which keeps the active chip's ring inside the scroll clip edge. */
const FLOW_EDGE_PADDING_PX = 6;

function enterDelayMs(index: number): number {
  return Math.min(index * ENTER_STAGGER_MS, ENTER_STAGGER_CAP_MS);
}

/** A step that finishes quietly stays a chip of its own this long, so the reader sees it land, and then it folds into the count above it. */
const FOLD_SETTLE_MS = 1200;

/** More quiet steps than this appearing in one update are a run being loaded, not a run advancing (a live update adds one or two), so they fold at once instead of flashing as separate chips first. */
const FOLD_BATCH_LIMIT = MIN_RAIL_FOLD;

/**
 * The ids of quiet steps that have had their moment as a chip and may now fold. Steps already quiet when the rail first renders, or when it is given another run, are settled at once. A step that becomes quiet later is settled after FOLD_SETTLE_MS, and one that stops being quiet (a phase that starts again) is dropped so it gets its moment again.
 */
function useSettledRailStageIds(stages: readonly RailStage[], scopeKey: string): ReadonlySet<string> {
  const quietIds = stages.filter(isQuietRailStage).map(stage => stage.id);
  const quietKey = quietIds.join('|');
  const settledRef = useRef<Set<string>>(new Set(quietIds));
  const scopeRef = useRef(scopeKey);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const [, refresh] = useReducer((version: number) => version + 1, 0);

  useEffect(() => {
    const timers = timersRef.current;
    const quiet = new Set(quietIds);
    if (scopeRef.current !== scopeKey) {
      scopeRef.current = scopeKey;
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
      settledRef.current = new Set(quiet);
      refresh();
      return;
    }
    let changed = false;
    for (const [id, timer] of timers) {
      if (quiet.has(id)) continue;
      clearTimeout(timer);
      timers.delete(id);
    }
    for (const id of settledRef.current) {
      if (quiet.has(id)) continue;
      settledRef.current.delete(id);
      changed = true;
    }
    const fresh = [...quiet].filter(id => !settledRef.current.has(id) && !timers.has(id));
    if (fresh.length > FOLD_BATCH_LIMIT) {
      for (const id of fresh) settledRef.current.add(id);
      changed = true;
    } else {
      for (const id of fresh) {
        timers.set(id, setTimeout(() => {
          timers.delete(id);
          settledRef.current.add(id);
          refresh();
        }, FOLD_SETTLE_MS));
      }
    }
    if (changed) refresh();
    // quietKey stands for quietIds: the effect runs when the set of quiet steps changes, not on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quietKey, scopeKey]);

  useEffect(() => () => {
    for (const timer of timersRef.current.values()) clearTimeout(timer);
    timersRef.current.clear();
  }, []);

  return scopeRef.current === scopeKey ? settledRef.current : new Set(quietIds);
}

/** The number on a fold chip. It is remounted when the number changes and, only then, plays a short tick so a step joining the fold is noticeable. */
function RailFoldCount({ count }: { count: number }) {
  const previousCount = useRef(count);
  const grew = count > previousCount.current;
  useEffect(() => {
    previousCount.current = count;
  }, [count]);
  return <span key={count} className={`agent-run-rail-fold-count${grew ? ' is-ticking' : ''}`}>{count > 99 ? '99+' : count}</span>;
}

const STARTING_STAGE: AgentRunOverviewPresentation['stages'][number] = {
  id: 'overview:starting',
  kind: 'phase',
  label: 'Starting',
  state: 'active',
  startedAt: '',
  artifactCount: 0,
};

export function AgentRunRail({
  overview,
  artifactCount = overview.artifactCount,
  runId,
  isProcessing = false,
  onExpand,
  runs = [],
  locationRunId,
  onNavigateRun,
  checklistRootId,
}: AgentRunRailProps) {
  const phaseCount = overview.stages.filter(stage => stage.kind === 'phase').length;
  const interactionCount = overview.stages.filter(stage => stage.kind === 'interaction').length;
  const documentLabel = artifactCount === 1 ? 'document' : 'documents';
  const interactionLabel = interactionCount > 0
    ? `, ${interactionCount} ${interactionCount === 1 ? 'exchange' : 'exchanges'} with you`
    : '';
  const ariaLabel = `Expand ${overview.terminalState} run overview, ${phaseCount} phases${interactionLabel}, ${artifactCount} ${documentLabel}`;
  const stages = overview.stages.length === 0 && isProcessing ? [STARTING_STAGE] : overview.stages;
  const settledStageIds = useSettledRailStageIds(stages, runId ?? 'run');
  const chips = foldRailStages(stages, settledStageIds);
  const showTurns = runs.length > 1 && Boolean(onNavigateRun);
  const expandedRunId = runs.some(run => run.id === runId)
    ? runId
    : runs.some(run => run.id === locationRunId)
      ? locationRunId
      : undefined;
  const expandedRef = useRef<HTMLDivElement>(null);
  const flowRef = useRef<HTMLSpanElement>(null);
  const followsEndRef = useRef(true);
  // Changes when a chip is added, changes state, or a fold chip's count grows, which are the moments the rail should keep the current step in view.
  const stageSignature = chips.map(chip => (isRailFold(chip) ? `${chip.id}:${chip.count}` : `${chip.id}:${chip.state}`)).join('|');

  useEffect(() => {
    const expanded = expandedRef.current;
    if (expanded) scrollVerticallyIntoView(expanded, { block: 'nearest' });
  }, [expandedRunId]);

  // A long run has more chips than fit, so the rail scrolls and follows the step that is active or waiting for the reader, or the last chip once the run has ended. A reader who scrolled up to look at earlier chips is not pulled back.
  useEffect(() => {
    if (!followsEndRef.current) return;
    const chips = Array.from(flowRef.current?.querySelectorAll<HTMLElement>('.agent-run-rail-flow-stage') ?? []);
    const current = [...chips].reverse().find(chip => chip.classList.contains('is-active') || chip.classList.contains('is-waiting'))
      ?? chips[chips.length - 1];
    const flow = flowRef.current;
    if (!current || !flow) return;
    if (flow.scrollHeight <= flow.clientHeight) {
      // The rail itself does not scroll here (an expanded turn inside the turns list), so the list that does scroll reveals the chip.
      scrollVerticallyIntoView(current, { block: 'nearest' });
      return;
    }
    // Layout offsets, not bounding rectangles: a chip that has just arrived is still scaled and shifted by its entrance animation, which would make a rectangle-based scroll stop short of the chip.
    const top = current.offsetTop - FLOW_EDGE_PADDING_PX;
    const bottom = current.offsetTop + current.offsetHeight + FLOW_EDGE_PADDING_PX;
    if (bottom > flow.scrollTop + flow.clientHeight) flow.scrollTop = bottom - flow.clientHeight;
    else if (top < flow.scrollTop) flow.scrollTop = top;
  }, [stageSignature]);

  const trackFollowing = (scroller: HTMLElement) => {
    followsEndRef.current = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - FOLLOW_END_SLACK_PX;
  };

  const flowToggle = (
    <button
      type="button"
      className="agent-run-rail-toggle"
      onClick={onExpand}
      aria-label={ariaLabel}
      aria-current={showTurns && expandedRunId === locationRunId ? 'location' : undefined}
    >
      <span
        className="agent-run-rail-flow"
        aria-hidden="true"
        ref={flowRef}
        onScroll={event => trackFollowing(event.currentTarget)}
      >
        {chips.map((chip, index) => {
          const timing = {
            '--run-rail-enter-delay': `${enterDelayMs(index)}ms`,
            '--run-rail-connector-delay': `${enterDelayMs(index + 1) + 130}ms`,
          } as CSSProperties;
          if (isRailFold(chip)) {
            return (
              <span
                className="agent-run-rail-flow-stage agent-run-rail-flow-stage--fold"
                key={`${runId ?? 'run'}:${chip.id}`}
                style={timing}
                data-tooltip={railFoldTitle(chip)}
                data-tooltip-placement="left"
              >
                <RailFoldCount count={chip.count} />
              </span>
            );
          }
          return (
            <span
              className={`agent-run-rail-flow-stage agent-run-rail-flow-stage--${chip.kind} is-${chip.state}${runControlStageClass(chip)}`}
              key={`${runId ?? 'run'}:${chip.id}`}
              style={timing}
              data-tooltip={railStageTitle(chip)}
              data-tooltip-placement="left"
            >
              <RailGlyph stage={chip} />
              {chip.artifactCount > 0 && <span className="agent-run-rail-artifact-mark" aria-label={`${chip.artifactCount} document${chip.artifactCount === 1 ? '' : 's'}`}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3.5h8l4 4v13H6zM14 3.5v5h4" /></svg></span>}
            </span>
          );
        })}
      </span>
    </button>
  );

  if (!showTurns || !onNavigateRun) {
    return (
      <aside className="agent-run-rail" aria-label="Run overview">
        {checklistRootId && <ChecklistRailPill rootTaskId={checklistRootId} />}
        {flowToggle}
      </aside>
    );
  }

  const expandedRun = runs.find(run => run.id === expandedRunId);
  const expandedStatus = expandedRun ? presentRunStatus(expandedRun) : undefined;
  const expandedTurn = (
    <div className="agent-run-rail-turn-expanded" ref={expandedRef}>
      {expandedRun && expandedStatus && (
        <span
          className={`agent-run-rail-turn-number${isRevisionNumber(expandedRun.displayNumber) ? ' is-revision' : ''}`}
          aria-hidden="true"
          data-tooltip={`${expandedRun.label}: ${expandedStatus.label}`}
          data-tooltip-placement="left"
        >
          {expandedRun.displayNumber || <ScheduledCheckGlyph />}
        </span>
      )}
      {flowToggle}
    </div>
  );

  return (
    <aside
      className="agent-run-rail agent-run-rail--turns"
      aria-label="Run overview"
      onClick={event => {
        if (!(event.target instanceof Element) || !event.target.closest('button')) {
          onExpand();
        }
      }}
    >
      {checklistRootId && <ChecklistRailPill rootTaskId={checklistRootId} />}
      <nav className="agent-run-rail-turns" aria-label="Turns" onScroll={event => trackFollowing(event.currentTarget)}>
        {runs.map(run => {
          if (run.id === expandedRunId) {
            return <Fragment key={run.id}>{expandedTurn}</Fragment>;
          }
          const status = presentRunStatus(run);
          const isLocation = run.id === locationRunId;
          return (
            <button
              type="button"
              key={run.id}
              className={`agent-run-rail-turn ${RUN_STATUS_TONE_CLASS[status.tone]}${isLocation ? ' is-location' : ''}${isRevisionNumber(run.displayNumber) ? ' is-revision' : ''}`}
              aria-current={isLocation ? 'location' : undefined}
              aria-label={`Go to ${run.label}, ${status.label}`}
              data-tooltip={`${run.label}: ${status.label}`}
              data-tooltip-placement="left"
              onClick={() => onNavigateRun(run.id)}
            >
              {run.displayNumber || <ScheduledCheckGlyph />}
            </button>
          );
        })}
        {expandedRunId === undefined && expandedTurn}
      </nav>
    </aside>
  );
}
