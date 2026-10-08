import type { MeetingActionProposalDTO, MeetingAnalysisResultDTO } from '../bridge/types';
import { useCopiedFlag } from '@shared/useCopyFeedback';
import { copyText, retryAnalysisModes } from '../bridge/meetingBridge';
import { MeetingMarkdown } from '../lib/markdown';
import { ANALYSIS_MODE_ORDER, formatModeResult, type AnalysisModeId } from '../lib/analysisModes';
import SuggestedActionWorkspace from './SuggestedActionWorkspace';

interface AnalysisResultsProps {
  result: MeetingAnalysisResultDTO;
  mode: AnalysisModeId;
  proposals: MeetingActionProposalDTO[];
}

export default function AnalysisResults({ result, mode, proposals }: AnalysisResultsProps) {
  const [sectionCopied, flashSectionCopied] = useCopiedFlag();
  const definition = ANALYSIS_MODE_ORDER.find((entry) => entry.id === mode);
  const failedModeIds = (result.failedModes ?? []).filter((failure) => failure.retryable).map((failure) => failure.mode);
  const modeOmissions = (result.safetyOmissions ?? []).filter((omission) => omission.mode === mode);
  const filename = result.filename ?? 'meeting-analysis';

  return (
    <div className={`meeting-analysis-results meeting-analysis-results--${mode.replace(/_/g, '-')}`}>
      {(result.failedModes?.length ?? 0) > 0 && (
        <div className="meeting-analysis-failure-banner" role="alert">
          <div>
            <strong>Some analyses failed</strong>
            <ul>
              {result.failedModes?.map((failure) => (
                <li key={failure.mode}>
                  {failure.mode}: {failure.message}
                  {failure.refusalExplanation && (
                    <details>
                      <summary>Provider restriction details</summary>
                      <p>{failure.refusalExplanation}</p>
                    </details>
                  )}
                </li>
              ))}
            </ul>
          </div>
          {failedModeIds.length > 0 && <button type="button" onClick={() => retryAnalysisModes(filename, failedModeIds)}>Retry failed analyses</button>}
        </div>
      )}
      {modeOmissions.length > 0 && (
        <div className="meeting-analysis-omission-notice" role="status">
          <p>Some transcript content was omitted because the selected provider declined to process it. Other processable sections were analyzed.</p>
          <p>{modeOmissions.length} omitted {modeOmissions.length === 1 ? 'range' : 'ranges'}: {modeOmissions.map(formatOmissionRange).join(', ')}</p>
        </div>
      )}

      <header className="meeting-analysis-mode-header">
        <div>
          <h2>{definition?.displayName ?? mode}</h2>
          <p className="meeting-analysis-mode-description">{definition?.description}</p>
          {result.fallbackModelUsed && (
            <span
              className="meeting-analysis-fallback-badge"
              title={`Preferred model was unreachable before any analysis mode succeeded; answered by local fallback: ${result.fallbackModelUsed}`}
            >
              Answered with local fallback
            </span>
          )}
        </div>
        <button
          type="button"
          className="meeting-analysis-mode-copy"
          title="Copy this section"
          aria-label="Copy this section"
          onClick={() => {
            copyText(formatModeResult(result, mode, proposals), true);
            flashSectionCopied();
          }}
        >
          {sectionCopied ? <CopiedSectionIcon /> : <CopySectionIcon />}
        </button>
      </header>

      {renderModeContent(result, mode, proposals)}
    </div>
  );
}

function renderModeContent(
  result: MeetingAnalysisResultDTO,
  mode: AnalysisModeId,
  proposals: MeetingActionProposalDTO[],
) {
  switch (mode) {
    case 'action_items':
      if (!result.actionItems || result.actionItems.length === 0) return <EmptyMode />;
      return (
        <div className="meeting-action-item-list" role="list">
          {result.actionItems.map((item, index) => (
            <div key={item.id} className="meeting-action-item" role="listitem">
              <span className="meeting-action-item-number" aria-hidden="true">{index + 1}</span>
              <div className="meeting-action-item-content">
                <strong>{item.task}</strong>
                {item.assignedTo && <span className="meeting-action-item-meta"><PersonCircleIcon />{item.assignedTo}</span>}
                {item.deadline && <span className="meeting-action-item-meta"><CalendarIcon />{item.deadline}</span>}
              </div>
            </div>
          ))}
        </div>
      );
    case 'suggested_actions':
      return <SuggestedActionWorkspace proposals={proposals} />;
    case 'summary':
      return result.summary ? <MeetingMarkdown content={result.summary} /> : <EmptyMode />;
    case 'decisions':
      if (!result.decisions || result.decisions.length === 0) return <EmptyMode />;
      return (
        <ol className="meeting-analysis-result-list">
          {result.decisions.map((decision) => (
            <li key={decision.id}>
              <strong>{decision.decision}</strong>
              {decision.rationale && <p>{decision.rationale}</p>}
            </li>
          ))}
        </ol>
      );
    case 'questions':
      if (!result.questionsAnswers || result.questionsAnswers.length === 0) return <EmptyMode />;
      return (
        <div>
          {result.questionsAnswers.map((qa) => (
            <div key={qa.id} className="meeting-analysis-qa-pair">
              <p><strong>Q:</strong> {qa.question}</p>
              <p><strong>A:</strong> {qa.answer}</p>
              {qa.asker && <p className="meeting-analysis-qa-meta">Asker: {qa.asker}</p>}
              {qa.responder && <p className="meeting-analysis-qa-meta">Responder: {qa.responder}</p>}
            </div>
          ))}
        </div>
      );
    case 'sentiment':
      if (!result.sentimentAnalysis) return <EmptyMode />;
      return (
        <div>
          <div className={`meeting-sentiment-summary meeting-sentiment-summary--${result.sentimentAnalysis.overallSentiment.toLowerCase()}`}>
            <div><span>Overall sentiment</span><strong>{result.sentimentAnalysis.overallSentiment}</strong></div>
            <div><span>Engagement level</span><strong>{result.sentimentAnalysis.engagementLevel}</strong></div>
          </div>
          {(result.sentimentAnalysis.positiveMoments?.length ?? 0) > 0 && (
            <div className="meeting-sentiment-moments meeting-sentiment-moments--positive">
              <h3>Positive Moments</h3>
              {result.sentimentAnalysis.positiveMoments?.map((moment) => <p key={moment.id}>{moment.description}<time>{formatTimestamp(moment.timestamp)}</time></p>)}
            </div>
          )}
          {(result.sentimentAnalysis.negativeMoments?.length ?? 0) > 0 && (
            <div className="meeting-sentiment-moments meeting-sentiment-moments--negative">
              <h3>Negative Moments</h3>
              {result.sentimentAnalysis.negativeMoments?.map((moment) => <p key={moment.id}>{moment.description}<time>{formatTimestamp(moment.timestamp)}</time></p>)}
            </div>
          )}
        </div>
      );
    case 'custom':
      if (!result.customAnalysis && !result.customInstructions?.trim()) return <EmptyMode />;
      return (
        <div>
          {result.customInstructions?.trim() && (
            <section className="meeting-analysis-custom-request">
              <h3>Request</h3>
              <p>{result.customInstructions}</p>
            </section>
          )}
          {result.customAnalysis && <MeetingMarkdown content={result.customAnalysis} />}
        </div>
      );
  }
}

function formatOmissionRange({ startTimestamp, endTimestamp }: { startTimestamp: number; endTimestamp: number }): string {
  const format = (seconds: number) => `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
  return startTimestamp === endTimestamp ? format(startTimestamp) : `${format(startTimestamp)}–${format(endTimestamp)}`;
}

function EmptyMode() {
  return <p className="meeting-analysis-empty-state">No results for this analysis.</p>;
}

function formatTimestamp(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
}

function CopySectionIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.2" />
      <path d="M10.5 5.5V3.8A1.3 1.3 0 0 0 9.2 2.5H3.8A1.3 1.3 0 0 0 2.5 3.8v5.4A1.3 1.3 0 0 0 3.8 10.5H5.5" />
    </svg>
  );
}

function CopiedSectionIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="m3 8.2 3.1 3.1L13 4.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PersonCircleIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
      <circle cx="8" cy="8" r="5.7" />
      <circle cx="8" cy="6.2" r="1.8" />
      <path d="M4.8 11.6c.5-1.8 1.6-2.7 3.2-2.7s2.7.9 3.2 2.7" strokeLinecap="round" />
    </svg>
  );
}

function CalendarIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.2" aria-hidden="true">
      <rect x="2.4" y="3.4" width="11.2" height="10" rx="1.5" />
      <path d="M5.2 1.8v3.1M10.8 1.8v3.1M2.7 6.2h10.6" strokeLinecap="round" />
    </svg>
  );
}
