import { useMemo, useState } from 'react';
import type { AgentTaskHistoryItem, StepDetailEntry } from '../../types';
import MarkdownRenderer from '../MarkdownRenderer';
import { CopyButtonGroup } from './CopyButtons';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import { ProgressStepsSection } from './ExecutionTimeline';
import { ReasoningWithInteractions } from '../interaction/InteractionExchange';
import { userInteractionsFromTimeline } from '../interaction/userInteractions';
import { FilesDisplay, ReferencePathsList } from './ResultAttachments';
import { formatBulletPoints, normalizeResultForPresentation, parseResult, splitRunDetails } from './resultContentUtils';
import { RunDetailsDisclosure } from './RunDetailsDisclosure';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';
import AgentTaskOriginChip from '../request/AgentTaskOriginChip';
import RequestDisplay from '../request/RequestDisplay';
import { plainMarkdownText } from '../../../../shared/plainMarkdownText';

export function HistoryCard({ item, isExpanded, onToggle, selectedDetailId, onSelectDetail }: {
  item: AgentTaskHistoryItem;
  isExpanded: boolean;
  onToggle: () => void;
  selectedDetailId?: string | null;
  onSelectDetail?: (detail: StepDetailEntry, isLatest: boolean) => void;
}) {
  const dateDisplayStyle = useDateDisplayStyle();
  const timeStr = useMemo(
    () => formatHistoryTimestamp(item.timestamp, dateDisplayStyle),
    [item.timestamp, dateDisplayStyle]
  );

  const presentationResult = useMemo(
    () => normalizeResultForPresentation(item.result, item.outcome),
    [item.outcome, item.result],
  );
  const histParsed = useMemo(() => parseResult(presentationResult), [presentationResult]);
  const userInteractions = useMemo(
    () => userInteractionsFromTimeline(item.executionTimeline, { runEnded: true }),
    [item.executionTimeline],
  );
  const histRunDetails = useMemo(() => splitRunDetails(histParsed.userSummary), [histParsed.userSummary]);
  const plainRequest = useMemo(() => plainMarkdownText(item.agentTaskText), [item.agentTaskText]);
  const collapsedPreview = useMemo(
    () => plainMarkdownText(histRunDetails.narrative).substring(0, 200),
    [histRunDetails.narrative],
  );
  const alertSeverityClass = item.resultSeverity === 'warning'
    ? 'history-card__alert--warning'
    : 'history-card__alert--error';
  const hasError = Boolean(item.errorMessage)
    && item.outcome?.trim().toLowerCase() !== 'completed_with_warnings';

  return (
    <div
      className={`agent-task-card history-card${isExpanded ? ' history-card--expanded' : ''}`}
      data-run-content={item.id}
      onClick={onToggle}
    >
      {!isExpanded ? (
        <div className="history-card__collapsed">
          <div className="history-card__collapsed-head">
            <span className="history-card__request-line">
              {plainRequest}
            </span>
            <span className="history-card__time">
              {timeStr}
            </span>
            <AgentTaskOriginChip originType={item.originType} originId={item.originId} />
          </div>
          <div className="history-card__preview">
            {collapsedPreview}
          </div>
          {item.files.length > 0 && (
            <div className="history-card__files">
              <svg width="10" height="10" viewBox="0 0 14 16" fill="var(--text-secondary)">
                <path d="M8 0H3a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 3 16h8a1.5 1.5 0 0 0 1.5-1.5V5L8 0z"/>
              </svg>
              <span className="history-card__files-label">
                {item.files.length} file{item.files.length === 1 ? '' : 's'}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div>
          <div className="history-card__head">
            <div className="history-card__head-main">
              <div className="history-card__request-full">
                {plainRequest}
              </div>
              <div className="history-card__time--expanded">
                {timeStr}
              </div>
              <AgentTaskOriginChip originType={item.originType} originId={item.originId} />
              {item.reference_paths.length > 0 && (
                <ReferencePathsList paths={item.reference_paths} />
              )}
            </div>
            <svg className="history-card__collapse-icon" width="11" height="11" viewBox="0 0 16 16" fill="var(--secondary)">
              <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM4.5 9.5L8 6l3.5 3.5"/>
            </svg>
          </div>

          <div className="history-card__divider" />

          {/* Expanded result — matches Swift's AgentTaskResultContentView */}
          <div className="history-card__body" onClick={e => e.stopPropagation()}>
            <RequestDisplay
              originalPrompt={item.agentTaskText}
              displayPromptMarkdown={item.displayPromptMarkdown}
              originType={item.originType}
              originId={item.originId}
            />
            {item.thinkingSegments?.length || userInteractions.length ? (
              <ReasoningWithInteractions
                segments={item.thinkingSegments || []}
                interactions={userInteractions}
                isLive={false}
                collapseForResponse={false}
              />
            ) : null}
            {/* Execution timeline from history (interleaved thinking + steps) */}
            {((item.executionTimeline && item.executionTimeline.length > 0) ||
              (item.executionSteps && item.executionSteps.length > 0)) && (
              <div data-run-section="activity">
                <ProgressStepsSection
                  steps={item.executionSteps || []}
                  timeline={item.executionTimeline || []}
                  stepDetails={item.stepDetails}
                  selectedDetailId={selectedDetailId}
                  onSelectDetail={onSelectDetail}
                  isProcessing={false}
                />
              </div>
            )}
            {/* Error banner for failed history items */}
            {hasError && (
              <div className={`history-card__alert ${alertSeverityClass}`}>
                <svg className="history-card__alert-icon" width="10" height="10" viewBox="0 0 16 16">
                  <path d="M8.982 1.566a1.13 1.13 0 0 0-1.964 0L.165 13.233c-.457.778.091 1.767.982 1.767h13.706c.891 0 1.439-.99.982-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
                </svg>
                {/* Same rationale as the live-result error banner above: the
                    agent's failure text is often markdown, so we render it
                    through MarkdownRenderer with the error color pinned on
                    the wrapper. Slightly smaller font here matches the
                    history-card density (status-small instead of callout) so
                    historical failures don't visually outweigh more recent
                    in-flight content. */}
                <div className="error-markdown history-card__alert-text">
                  <MarkdownRenderer content={item.errorMessage || ''} />
                </div>
              </div>
            )}
            <div className="history-card__result-heading" data-run-section="result">
              <span className="history-card__result-heading-text">
                {hasError ? 'Partial Result:' : 'Result:'}
              </span>
            </div>
            {histParsed.technicalSteps.length > 0 &&
              !(item.executionTimeline?.length || item.executionSteps?.length) && (
              <ExecutionSteps stepsContent={histParsed.technicalSteps} />
            )}
            <div className="history-card__result">
              <CopyButtonGroup text={presentationResult} />
              <MarkdownRenderer content={formatBulletPoints(histRunDetails.narrative)} />
            </div>
            <RunDetailsDisclosure details={histRunDetails.details} />
            <FilesDisplay files={item.files} resultText={presentationResult} />
          </div>
        </div>
      )}
    </div>
  );
}

function ExecutionSteps({ stepsContent }: { stepsContent: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="history-card__steps">
      <div
        className="execution-steps-header"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="history-card__steps-title">
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="6" cy="6" r="4.5" />
            <circle cx="11" cy="11" r="3.5" />
            <path d="M6 4v2h2M11 9.5v1.5h1.5" />
          </svg>
          <span className="history-card__steps-label">
            Execution Steps
          </span>
        </div>
        <ExecutionDisclosureChevron expanded={expanded} />
      </div>

      {expanded && (
        <div className="execution-steps-body history-card__steps-body">
          <pre className="history-card__steps-pre">
            {stepsContent}
          </pre>
        </div>
      )}
    </div>
  );
}
