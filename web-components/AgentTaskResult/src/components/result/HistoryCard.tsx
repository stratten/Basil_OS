import { useMemo, useState } from 'react';
import type { AgentTaskHistoryItem, StepDetailEntry } from '../../types';
import MarkdownRenderer from '../MarkdownRenderer';
import { CopyButtonGroup } from './CopyButtons';
import ExecutionDisclosureChevron from '@shared/ExecutionDisclosureChevron';
import { ProgressStepsSection } from './ExecutionTimeline';
import { ThinkingSegments } from './ThinkingSections';
import { FilesDisplay, ReferencePathsList } from './ResultAttachments';
import { formatBulletPoints, normalizeResultForPresentation, parseResult } from './resultContentUtils';
import { formatHistoryTimestamp, useDateDisplayStyle } from '../../app/dateDisplay';
import AgentTaskOriginChip from '../request/AgentTaskOriginChip';
import RequestDisplay from '../request/RequestDisplay';

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
  const alertColor = item.resultSeverity === 'warning' ? 'var(--warning-base)' : 'var(--error-base)';
  const alertBorder = item.resultSeverity === 'warning'
    ? '1px solid rgba(198, 121, 0, 0.28)'
    : '1px solid rgba(139, 0, 0, 0.2)';
  const alertBackground = item.resultSeverity === 'warning'
    ? 'rgba(198, 121, 0, 0.06)'
    : 'rgba(139, 0, 0, 0.05)';
  const hasError = Boolean(item.errorMessage)
    && item.outcome?.trim().toLowerCase() !== 'completed_with_warnings';

  return (
    <div
      className="agent-task-card"
      style={{
        background: isExpanded ? 'var(--background-primary)' : 'rgba(var(--background-secondary-rgb, 246,246,246), 0.5)',
        borderWidth: 1,
        borderColor: isExpanded ? 'rgba(0,48,135,0.3)' : 'rgba(0,48,135,0.15)',
        overflow: 'hidden',
      }}
      onClick={onToggle}
    >
      {!isExpanded ? (
        <div style={{ padding: 'var(--padding-m)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--padding-s)' }}>
            <svg width="11" height="11" viewBox="0 0 16 16" fill="var(--success-base)" style={{ flexShrink: 0 }}>
              <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm3.41 5.09a.75.75 0 0 0-1.06-.04L7.2 8.04 5.64 6.59a.75.75 0 1 0-1.02 1.1l2.1 1.95a.75.75 0 0 0 1.04-.03l3.65-3.46a.75.75 0 0 0-.04-1.06z"/>
            </svg>
            <span style={{
              fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-small)',
              color: 'var(--text-secondary)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {item.agentTaskText}
            </span>
            <span style={{
              fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)',
              color: 'var(--text-secondary)', flexShrink: 0,
            }}>
              {timeStr}
            </span>
            <AgentTaskOriginChip originType={item.originType} originId={item.originId} />
          </div>
          <div style={{
            fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)',
            color: 'var(--text-secondary)', marginTop: 'var(--padding-s)',
            display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
            wordBreak: 'break-word', userSelect: 'text',
          }}>
            {histParsed.userSummary.substring(0, 200)}
          </div>
          {item.files.length > 0 && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 'var(--padding-xs)', marginTop: 'var(--padding-s)',
            }}>
              <svg width="10" height="10" viewBox="0 0 14 16" fill="var(--text-secondary)">
                <path d="M8 0H3a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 3 16h8a1.5 1.5 0 0 0 1.5-1.5V5L8 0z"/>
              </svg>
              <span style={{
                fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)',
                color: 'var(--text-secondary)',
              }}>
                {item.files.length} file{item.files.length === 1 ? '' : 's'}
              </span>
            </div>
          )}
        </div>
      ) : (
        <div>
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 'var(--padding-s)',
            padding: 'var(--padding-m) var(--padding-l) 0',
          }}>
            <svg width="11" height="11" viewBox="0 0 16 16" fill="var(--success-base)" style={{ marginTop: 2, flexShrink: 0 }}>
              <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm3.41 5.09a.75.75 0 0 0-1.06-.04L7.2 8.04 5.64 6.59a.75.75 0 1 0-1.02 1.1l2.1 1.95a.75.75 0 0 0 1.04-.03l3.65-3.46a.75.75 0 0 0-.04-1.06z"/>
            </svg>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--font-family-light)', fontSize: 10, color: 'var(--text-primary)', wordBreak: 'break-word' }}>
                {item.agentTaskText}
              </div>
              <div style={{ fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)', color: 'var(--text-secondary)', marginTop: 2 }}>
                {timeStr}
              </div>
              <AgentTaskOriginChip originType={item.originType} originId={item.originId} />
              {item.reference_paths.length > 0 && (
                <ReferencePathsList paths={item.reference_paths} />
              )}
            </div>
            <svg width="11" height="11" viewBox="0 0 16 16" fill="var(--secondary)" style={{ flexShrink: 0, marginTop: 2 }}>
              <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zM4.5 9.5L8 6l3.5 3.5"/>
            </svg>
          </div>

          <div style={{ height: 1, background: 'var(--separator-color)', margin: 'var(--padding-m) var(--padding-l) 0' }} />

          {/* Expanded result — matches Swift's AgentTaskResultContentView */}
          <div style={{ padding: 'var(--padding-m) var(--padding-l)' }} onClick={e => e.stopPropagation()}>
            <RequestDisplay
              originalPrompt={item.agentTaskText}
              displayPromptMarkdown={item.displayPromptMarkdown}
              originType={item.originType}
              originId={item.originId}
            />
            {item.thinkingSegments?.length ? (
              <ThinkingSegments
                segments={item.thinkingSegments}
                isLive={false}
                collapseForResponse={false}
              />
            ) : null}
            {/* Execution timeline from history (interleaved thinking + steps) */}
            {((item.executionTimeline && item.executionTimeline.length > 0) ||
              (item.executionSteps && item.executionSteps.length > 0)) && (
              <ProgressStepsSection
                steps={item.executionSteps || []}
                timeline={item.executionTimeline || []}
                stepDetails={item.stepDetails}
                selectedDetailId={selectedDetailId}
                onSelectDetail={onSelectDetail}
                isProcessing={false}
              />
            )}
            {/* Error banner for failed history items */}
            {hasError && (
              <div style={{
                display: 'flex', alignItems: 'flex-start', gap: 'var(--padding-s)',
                padding: 'var(--padding-s) var(--padding-m)',
                marginBottom: 'var(--padding-s)',
                background: alertBackground,
                borderRadius: 'var(--corner-radius-medium, 8px)',
                border: alertBorder,
              }}>
                <svg width="10" height="10" viewBox="0 0 16 16" fill={alertColor} style={{ flexShrink: 0, marginTop: 2 }}>
                  <path d="M8.982 1.566a1.13 1.13 0 0 0-1.964 0L.165 13.233c-.457.778.091 1.767.982 1.767h13.706c.891 0 1.439-.99.982-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"/>
                </svg>
                {/* Same rationale as the live-result error banner above: the
                    agent's failure text is often markdown, so we render it
                    through MarkdownRenderer with the error color pinned on
                    the wrapper. Slightly smaller font here matches the
                    history-card density (status-small instead of callout) so
                    historical failures don't visually outweigh more recent
                    in-flight content. */}
                <div className="error-markdown" style={{
                  color: alertColor,
                  fontFamily: 'var(--font-family-light)',
                  fontSize: 'var(--font-size-status-small)',
                  userSelect: 'text',
                  flex: 1,
                  minWidth: 0,
                }}>
                  <MarkdownRenderer content={item.errorMessage || ''} />
                </div>
              </div>
            )}
            <div style={{ marginBottom: 6 }}>
              <span style={{ fontFamily: 'var(--font-family-light)', fontSize: 'var(--font-size-body)', color: 'var(--text-primary)' }}>
                {hasError ? 'Partial Result:' : 'Result:'}
              </span>
            </div>
            {histParsed.technicalSteps.length > 0 &&
              !(item.executionTimeline?.length || item.executionSteps?.length) && (
              <ExecutionSteps stepsContent={histParsed.technicalSteps} />
            )}
            <div style={{
              padding: 'var(--padding-m)', background: 'var(--background-primary)',
              borderRadius: 'var(--corner-radius-medium, 8px)',
              border: '1px solid rgba(0,48,135,0.2)',
              overflow: 'hidden', wordBreak: 'break-word',
              position: 'relative',
            }}>
              <CopyButtonGroup text={presentationResult} />
              <MarkdownRenderer content={formatBulletPoints(histParsed.userSummary)} />
            </div>
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
