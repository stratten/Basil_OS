import type { DisplayableAgentTask, StepDetailEntry } from '../types';
import MarkdownRenderer from './MarkdownRenderer';
import { useState, useMemo, useRef, useEffect, useCallback } from 'react';
import { CopyButtonGroup } from './result/CopyButtons';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import { ProgressStepsSection } from './result/ExecutionTimeline';
import { FilesDisplay, ReferencePathsList } from './result/ResultAttachments';
import { HistoryCard } from './result/HistoryCard';
import { ThinkingSection } from './result/ThinkingSections';
import { InteractionExchange, ReasoningWithInteractions } from './interaction/InteractionExchange';
import { userInteractionsFromTimeline } from './interaction/userInteractions';
import { hasVisibleActivity } from './result/activityDockPresentation';
import {
  formatBulletPoints,
  isUserFacingResponseStreaming,
  normalizeResultForPresentation,
  parseResult,
  splitRunDetails,
} from './result/resultContentUtils';
import { RunDetailsDisclosure } from './result/RunDetailsDisclosure';
import RequestDisplay from './request/RequestDisplay';
import { saveAgentTaskAsSkill, submitAgentTaskFeedback } from '../services/api';
import { DelegatedProviderReportCards } from './artifacts/DelegatedProviderReportCards';
import PresenceRegion from '@shared/PresenceRegion';
import { TurnLabel } from './result/TurnLabel';
import { resolveTurnStatus } from './result/turnPresentation';
import { agentTaskRunLabel } from './run/agentTaskRunFocus';
import { RunStatusCard } from './run/RunStatusCard';
import { deriveRunPhase, isActivityInCard, showsRunStatusCard } from './run/runPhase';
import { prefersReducedMotion, type RunNavigationRequest } from './run/runNavigation';
import { useRunNavigationScroll } from './run/useRunNavigationScroll';

interface Props {
  agentTask: DisplayableAgentTask;
  onRetry: (modelId?: string) => void;
  onContinue: () => void;
  selectedDetailId?: string | null;
  selectedDetailOwnerId?: string | null;
  onSelectDetail?: (ownerTaskId: string, detail: StepDetailEntry, isLatest: boolean) => void;
  focusedRunId?: string | null;
  onFocusRun?: (runId: string) => void;
  navigationRequest?: RunNavigationRequest | null;
  onLocationChange?: (runId: string) => void;
}

type ResultActionMessage = {
  kind: 'info' | 'success' | 'error';
  text: string;
};

export default function ResultContent({
  agentTask,
  onRetry,
  onContinue,
  selectedDetailId,
  selectedDetailOwnerId,
  onSelectDetail,
  focusedRunId,
  onFocusRun,
  navigationRequest,
  onLocationChange,
}: Props) {
  const hasTurnChain = agentTask.agentTaskHistory.length > 0;
  const currentRunId = agentTask.currentTurnTaskId || agentTask.agentTaskId;
  const presentationResult = useMemo(
    () => normalizeResultForPresentation(agentTask.result, agentTask.outcome),
    [agentTask.outcome, agentTask.result],
  );
  const parsed = useMemo(() => parseResult(presentationResult), [presentationResult]);
  const runDetails = useMemo(() => splitRunDetails(parsed.userSummary), [parsed.userSummary]);
  const hasTechnicalSteps = parsed.technicalSteps.length > 0;
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [skillPreview, setSkillPreview] = useState<{ title: string; body: string; when_to_use: string; triggers: string[] } | null>(null);
  const [isSkillSaving, setIsSkillSaving] = useState(false);
  const [skillSaveMessage, setSkillSaveMessage] = useState<ResultActionMessage | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<ResultActionMessage | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const userIsReadingEarlierRef = useRef(false);
  const [hasUnreadLiveContent, setHasUnreadLiveContent] = useState(false);
  const isProcessing =
    agentTask.status === 'processing' ||
    agentTask.status === 'routing' ||
    agentTask.status === 'capturing';
  const latestThinkingSegmentText = agentTask.thinkingSegments[agentTask.thinkingSegments.length - 1]?.text;

  useEffect(() => {
    if (!isProcessing || !scrollRef.current) return;
    if (!userIsReadingEarlierRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      return;
    }
    setHasUnreadLiveContent(true);
  }, [
    agentTask.thinking,
    agentTask.result,
    agentTask.currentStep,
    agentTask.thinkingSegments.length,
    latestThinkingSegmentText,
    agentTask.executionTimeline.length,
    agentTask.progressSteps.length,
    isProcessing,
  ]);

  useEffect(() => {
    setSkillPreview(null);
    setSkillSaveMessage(null);
    setIsSkillSaving(false);
    userIsReadingEarlierRef.current = false;
    setHasUnreadLiveContent(false);
  }, [agentTask.agentTaskId]);

  const hasThinkingSegments = agentTask.thinkingSegments.length > 0;
  const phase = deriveRunPhase(agentTask);
  const runEnded = phase.kind === 'settled' || phase.kind === 'canceled' || phase.kind === 'verifying';
  const userInteractions = useMemo(
    () => userInteractionsFromTimeline(agentTask.executionTimeline, { runEnded }),
    [agentTask.executionTimeline, runEnded],
  );
  const hasResult = Boolean(agentTask.result);
  const responseIsStreaming = isUserFacingResponseStreaming(
    agentTask.isStreaming,
    agentTask.result,
  );
  const resultIsProvisional = phase.kind === 'verifying';
  const resultIsPartial = phase.kind === 'canceled' || (phase.kind === 'settled' && phase.outcome !== 'success');
  const canSaveAsSkill = agentTask.status === 'completed' && !agentTask.isStreaming && hasResult && phase.kind === 'settled';
  const hasActivity = hasVisibleActivity(
    agentTask.executionTimeline,
    agentTask.progressSteps,
  );
  const activityInCard = isActivityInCard(phase);
  const showInlineCompletedActivity = hasActivity && !activityInCard;
  const showStatusCard = activityInCard || showsRunStatusCard(phase);
  const onJumpToLatestContent = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    userIsReadingEarlierRef.current = false;
    setHasUnreadLiveContent(false);
    if (prefersReducedMotion()) {
      el.scrollTop = el.scrollHeight;
      return;
    }
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
  }, []);
  const priorRunIds = useMemo(
    () => agentTask.agentTaskHistory.map(item => item.id),
    [agentTask.agentTaskHistory],
  );
  const { isProgrammaticScrollActive, releaseProgrammaticScroll, reportScrollLocation } = useRunNavigationScroll({
    scrollRef,
    currentRunId,
    priorRunIds,
    expandedCardId,
    setExpandedCardId,
    navigationRequest,
    onLocationChange,
    userIsReadingEarlierRef,
    onJumpToLatestContent,
  });

  const handleMainContentScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
    if (!isProgrammaticScrollActive()) {
      userIsReadingEarlierRef.current = !atBottom;
    }
    if (atBottom) {
      setHasUnreadLiveContent(false);
    }
    reportScrollLocation(el, atBottom);
  }, [isProgrammaticScrollActive, reportScrollLocation]);

  const handlePreviewSkill = () => {
    setIsSkillSaving(true);
    setSkillSaveMessage({ kind: 'info', text: 'Generating skill preview...' });
    saveAgentTaskAsSkill(agentTask.agentTaskId, { preview_only: true })
      .then(response => {
        setSkillPreview({
          title: response.title,
          body: response.body,
          when_to_use: response.when_to_use,
          triggers: response.triggers,
        });
        setSkillSaveMessage({ kind: 'success', text: 'Skill preview ready to review.' });
      })
      .catch(error => setSkillSaveMessage({ kind: 'error', text: errorMessageFromUnknown(error) }))
      .finally(() => setIsSkillSaving(false));
  };

  const handleSaveSkill = () => {
    if (!skillPreview) return;
    setIsSkillSaving(true);
    setSkillSaveMessage({ kind: 'info', text: 'Saving skill...' });
    saveAgentTaskAsSkill(agentTask.agentTaskId, {
      title: skillPreview.title,
      body: skillPreview.body,
      when_to_use: skillPreview.when_to_use,
      triggers: skillPreview.triggers,
      preview_only: false,
    })
      .then(response => {
        setSkillSaveMessage({ kind: 'success', text: response.slug ? `Saved skill: ${response.slug}` : 'Saved skill.' });
        setSkillPreview(null);
      })
      .catch(error => setSkillSaveMessage({ kind: 'error', text: errorMessageFromUnknown(error) }))
      .finally(() => setIsSkillSaving(false));
  };

  const handleSubmitFeedback = (rating: -1 | 1) => {
    setFeedbackMessage(null);
    submitAgentTaskFeedback(agentTask.agentTaskId, { user_rating: rating })
      .then(() => setFeedbackMessage({
        kind: 'success',
        text: rating > 0 ? 'Thanks. Basil will prefer workflows like this.' : 'Thanks. Basil will avoid treating this as a reusable pattern.',
      }))
      .catch(error => setFeedbackMessage({ kind: 'error', text: errorMessageFromUnknown(error) }));
  };

  return (
    <div className="result-content-shell">
      <div
        className="main-content"
        ref={scrollRef}
        onScroll={handleMainContentScroll}
        onWheel={releaseProgrammaticScroll}
        onTouchMove={releaseProgrammaticScroll}
        onPointerDown={releaseProgrammaticScroll}
        onKeyDown={releaseProgrammaticScroll}
      >
      {agentTask.agentTaskHistory.map((item, index) => (
        <div className="turn-block" key={item.id}>
          <TurnLabel
            runId={item.id}
            label={agentTaskRunLabel(index)}
            status={resolveTurnStatus(item)}
            isFocused={focusedRunId === item.id}
            onFocusRun={onFocusRun}
          />
          <HistoryCard
            item={item}
            isExpanded={expandedCardId === item.id}
            onToggle={() => setExpandedCardId(expandedCardId === item.id ? null : item.id)}
            selectedDetailId={selectedDetailOwnerId === item.id ? selectedDetailId : null}
            onSelectDetail={(detail, isLatest) => onSelectDetail?.(item.id, detail, isLatest)}
          />
        </div>
      ))}

      {hasTurnChain && (
        <TurnLabel
          runId={currentRunId}
          label={agentTaskRunLabel(agentTask.agentTaskHistory.length)}
          status={resolveTurnStatus(agentTask)}
          timestamp={agentTask.timestamp}
          isFocused={focusedRunId === currentRunId}
          onFocusRun={onFocusRun}
        />
      )}

      {agentTask.originalPrompt && (
        <>
          <RequestDisplay
            originalPrompt={agentTask.originalPrompt}
            displayPromptMarkdown={agentTask.displayPromptMarkdown}
            originType={agentTask.originType}
            originId={agentTask.originId}
          />
          {agentTask.referencePaths.length > 0 && (
            <ReferencePathsList paths={agentTask.referencePaths} />
          )}
        </>
      )}

      <PresenceRegion visible={Boolean(agentTask.showWorkflowPlan && agentTask.workflowPlan)} className="result-presence-region">
        {agentTask.workflowPlan && <WorkflowPlanSection plan={agentTask.workflowPlan} />}
      </PresenceRegion>

      <PresenceRegion visible={Boolean(hasThinkingSegments || agentTask.thinking || userInteractions.length > 0)} className="result-presence-region">
        {hasThinkingSegments || (userInteractions.length > 0 && !agentTask.thinking) ? (
          <ReasoningWithInteractions
            segments={agentTask.thinkingSegments}
            interactions={userInteractions}
            isLive={isProcessing && !agentTask.thinkingComplete}
            isRunActive={isProcessing}
            collapseForResponse={responseIsStreaming}
            runComplete={phase.kind === 'settled' || phase.kind === 'canceled'}
          />
        ) : agentTask.thinking ? (
          <>
            {userInteractions.map(interaction => (
              <InteractionExchange key={interaction.entryId} interaction={interaction} />
            ))}
            <ThinkingSection
              thinking={agentTask.thinking}
              isLive={isProcessing && !agentTask.thinkingComplete}
              defaultExpanded={false}
              collapseForResponse={responseIsStreaming}
            />
          </>
        ) : null}
      </PresenceRegion>

      <PresenceRegion visible={showInlineCompletedActivity} className="result-presence-region">
        <div data-run-section="activity">
          <ProgressStepsSection
            key={`activity-inline-${agentTask.agentTaskId}`}
            presentation="inline"
            steps={agentTask.progressSteps}
            timeline={agentTask.executionTimeline}
            stepDetails={agentTask.stepDetails}
            selectedDetailId={selectedDetailOwnerId === agentTask.agentTaskId ? selectedDetailId : null}
            onSelectDetail={(detail, isLatest) => onSelectDetail?.(agentTask.agentTaskId, detail, isLatest)}
            isProcessing={isProcessing}
          />
        </div>
      </PresenceRegion>

      <PresenceRegion visible={hasResult} className="result-presence-region result-presence-region--response">
        <div>
          {hasTechnicalSteps && agentTask.executionTimeline.length === 0 && agentTask.progressSteps.length === 0 && (
            <ExecutionSteps stepsContent={parsed.technicalSteps} />
          )}

          <div className="result-header" data-run-section="result">
            <span className="result-label">{resultIsPartial ? 'Partial Result:' : 'Result:'}</span>
            {resultIsProvisional && (
              <span className="result-fallback-badge result-provisional-badge" title="This result is shown while Basil checks it against your request">
                Provisional
              </span>
            )}
            {agentTask.reasoningFallbackModelUsed && (
              <span
                className="result-fallback-badge"
                title={`Preferred model was unreachable before any response; answered by local fallback: ${agentTask.reasoningFallbackModelUsed}`}
              >
                Answered with local fallback
              </span>
            )}
          </div>
          <div className="result-container" style={{ position: 'relative' }}>
            <CopyButtonGroup text={presentationResult} />
            <MarkdownRenderer
              content={formatBulletPoints(runDetails.narrative)}
              isStreaming={agentTask.isStreaming}
            />
          </div>
          <RunDetailsDisclosure
            key={`run-details-${agentTask.currentTurnTaskId || agentTask.agentTaskId}`}
            details={runDetails.details}
          />
          <FilesDisplay files={agentTask.structuredFiles} resultText={presentationResult} />
          <DelegatedProviderReportCards cards={agentTask.delegatedProviderReportCards} />
          {canSaveAsSkill && (
            <div className="result-actions result-actions--feedback">
              <button
                className="action-icon-btn action-icon-btn--save"
                onClick={handlePreviewSkill}
                disabled={isSkillSaving}
                aria-label={isSkillSaving ? 'Generating skill preview' : 'Save as skill'}
                title={isSkillSaving ? 'Generating skill preview...' : 'Save this result as a reusable skill (preview first)'}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M6.5 19.5h11v-11l-2-2h-9v13Z" />
                  <path d="M9 19.5v-6h6v6" />
                  <path d="M9 9h5" />
                </svg>
              </button>
              <button className="action-icon-btn action-icon-btn--good" onClick={() => handleSubmitFeedback(1)} aria-label="Good result" title="This result was helpful">
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="m5 12.5 4.3 4.3L19 7.2" />
                </svg>
              </button>
              <button className="action-icon-btn action-icon-btn--bad" onClick={() => handleSubmitFeedback(-1)} aria-label="Not useful" title="This result wasn't helpful">
                <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M7 7l10 10" />
                  <path d="M17 7 7 17" />
                </svg>
              </button>
            </div>
          )}
          <PresenceRegion visible={Boolean(feedbackMessage)} className="result-presence-region">
            {feedbackMessage && <ResultActionMessageView message={feedbackMessage} />}
          </PresenceRegion>
          <PresenceRegion visible={Boolean(skillSaveMessage)} className="result-presence-region">
            {skillSaveMessage && <ResultActionMessageView message={skillSaveMessage} />}
          </PresenceRegion>
          <PresenceRegion visible={Boolean(skillPreview)} className="result-presence-region">
            {skillPreview && (
            <div className="result-container" style={{ marginTop: 'var(--padding-s)' }}>
              <div className="result-header">
                <span className="result-label">Skill Preview:</span>
              </div>
              <input
                value={skillPreview.title}
                onChange={event => setSkillPreview(current => current ? { ...current, title: event.target.value } : current)}
                style={{
                  background: 'var(--background-secondary)',
                  border: '0.5px solid var(--separator-color)',
                  borderRadius: 'var(--corner-radius-small)',
                  color: 'var(--text-primary)',
                  marginBottom: 'var(--padding-s)',
                  padding: '8px',
                  width: '100%',
                }}
              />
              <textarea
                value={skillPreview.body}
                onChange={event => setSkillPreview(current => current ? { ...current, body: event.target.value } : current)}
                style={{
                  background: 'var(--background-secondary)',
                  border: '0.5px solid var(--separator-color)',
                  borderRadius: 'var(--corner-radius-small)',
                  color: 'var(--text-primary)',
                  minHeight: 220,
                  padding: '8px',
                  resize: 'vertical',
                  width: '100%',
                }}
              />
              <div className="result-actions">
                <button className="action-btn primary" onClick={handleSaveSkill} disabled={isSkillSaving}>
                  Save skill
                </button>
                <button className="action-btn secondary" onClick={() => setSkillPreview(null)} disabled={isSkillSaving}>
                  Cancel
                </button>
              </div>
            </div>
            )}
          </PresenceRegion>
        </div>
      </PresenceRegion>

      </div>

      {showStatusCard && (
        <RunStatusCard
          key={`run-status-${agentTask.agentTaskId}`}
          agentTask={agentTask}
          phase={phase}
          showTrail={activityInCard}
          selectedDetailId={selectedDetailOwnerId === agentTask.agentTaskId ? selectedDetailId : null}
          onSelectDetail={(detail, isLatest) => onSelectDetail?.(agentTask.agentTaskId, detail, isLatest)}
          hasUnreadLiveContent={hasUnreadLiveContent}
          onJumpToLatestContent={onJumpToLatestContent}
          onRetry={onRetry}
          onContinue={onContinue}
        />
      )}
    </div>
  );
}

function ResultActionMessageView({ message }: { message: ResultActionMessage }) {
  return (
    <div className={`result-action-message ${message.kind}`} role={message.kind === 'error' ? 'alert' : 'status'}>
      {message.text}
    </div>
  );
}

function errorMessageFromUnknown(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

function ExecutionSteps({ stepsContent }: { stepsContent: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div style={{ padding: '0 var(--padding-xs)', marginBottom: 'var(--padding-m)' }}>
      <div
        className="execution-steps-header"
        onClick={() => setExpanded(!expanded)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="6" cy="6" r="4.5" />
            <circle cx="11" cy="11" r="3.5" />
            <path d="M6 4v2h2M11 9.5v1.5h1.5" />
          </svg>
          <span style={{
            fontFamily: 'var(--font-family-medium)',
            fontSize: 'var(--font-size-status-small)',
            color: 'var(--text-tertiary)',
          }}>
            Execution Steps
          </span>
        </div>
        <ExecutionDisclosureChevron expanded={expanded} />
      </div>

      {expanded && (
        <div className="execution-steps-body" style={{ maxHeight: 200, overflow: 'auto' }}>
          <pre style={{
            fontFamily: 'var(--font-family-light)',
            fontSize: 'var(--font-size-status-small)',
            color: 'var(--text-secondary)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            margin: 0,
            padding: 'var(--padding-s)',
            userSelect: 'text',
          }}>
            {stepsContent}
          </pre>
        </div>
      )}
    </div>
  );
}

function WorkflowPlanSection({ plan }: { plan: NonNullable<DisplayableAgentTask['workflowPlan']> }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="workflow-plan">
      <div
        className="workflow-plan-header"
        onClick={() => setExpanded(!expanded)}
      >
        <span>Workflow Plan</span>
        <span>{expanded ? '▼' : '▶'}</span>
      </div>
      {expanded && (
        <div className="workflow-plan-body">
          {plan.todos.map((todo) => (
            <div key={todo.id} className="workflow-todo">
              <div className="workflow-todo-title">{todo.title}</div>
              {todo.steps.map((step) => (
                <div key={step.id} className="workflow-step">
                  <div className={`step-status-icon ${step.status || 'pending'}`} />
                  <span>{step.description}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
