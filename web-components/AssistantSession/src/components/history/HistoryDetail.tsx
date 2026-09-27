import { useEffect, useState } from 'react';
import { CollapsibleSection } from './CollapsibleSection';
import { HistoryActionButtons } from './ActionButtons';
import { MarkdownView } from '../MarkdownView';
import { formatDetailTimestamp, formatRefinementTime } from '../../lib/historyTimestamps';
import { splitThinking, stripThinking } from '../../lib/thinkingExtractor';
import { saveWritingSample, type AssistantOutputHistoryDetail } from '../../services/historyApi';
import { copyHistoryMarkdown, copyHistoryRichText, refineFromHistory } from '../../bridge/historyBridge';
import { NativeSymbol } from '../NativeSymbol';

export function HistoryDetail({
  entry,
  baseUrl,
  loading,
  nativeActionError,
  onClearNativeActionError,
}: {
  entry: AssistantOutputHistoryDetail | null;
  baseUrl: string;
  loading: boolean;
  nativeActionError: string | null;
  onClearNativeActionError: () => void;
}) {
  const [isEditMode, setIsEditMode] = useState(false);
  const [editedContent, setEditedContent] = useState('');
  const [appliedOutput, setAppliedOutput] = useState<string | null>(null);
  const [sampleSaved, setSampleSaved] = useState(false);
  const [savingSample, setSavingSample] = useState(false);
  const [hovering, setHovering] = useState(false);
  const [copiedKind, setCopiedKind] = useState<'richText' | 'markdown' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    setIsEditMode(false);
    setEditedContent('');
    setAppliedOutput(null);
    setSampleSaved(false);
    setSavingSample(false);
    setActionError(null);
  }, [entry?.id]);

  useEffect(() => {
    if (nativeActionError) setActionError(nativeActionError);
  }, [nativeActionError]);

  if (loading) {
    return (
      <div className="assistant-output-history-detail assistant-output-history-detail--empty">
        Loading AssistantSession output...
      </div>
    );
  }

  if (!entry) {
    return (
      <div className="assistant-output-history-detail assistant-output-history-detail--empty">
        Select a AssistantSession output to view details
      </div>
    );
  }

  const displayEntry = appliedOutput == null ? entry : { ...entry, outputText: appliedOutput };
  const latestRaw = displayEntry.refinements[displayEntry.refinements.length - 1]?.output ?? displayEntry.outputText;
  const latest = splitThinking(latestRaw);
  const outputLabel = displayEntry.refinements.length > 0
    ? `Latest (Refinement #${displayEntry.refinements.length})`
    : 'AssistantSession Output';

  const flash = (kind: 'richText' | 'markdown') => {
    setCopiedKind(kind);
    window.setTimeout(() => {
      setCopiedKind((current) => (current === kind ? null : current));
    }, 1500);
  };

  const copy = (kind: 'richText' | 'markdown') => {
    if (kind === 'richText') {
      copyHistoryRichText(latest.content);
    } else {
      copyHistoryMarkdown(latest.content);
    }
    flash(kind);
  };

  return (
    <div className="assistant-output-history-detail">
      <div className="assistant-output-history-detail__header">
        <span className="assistant-output-history-detail__badge">
          Dill{displayEntry.inputModality ? ` · ${displayEntry.inputModality}` : ''}
        </span>
        {displayEntry.appName && <span className="assistant-output-history-detail__app">in {displayEntry.appName}</span>}
        <span className="assistant-output-history-detail__time">
          {formatDetailTimestamp(displayEntry.timestamp)}
          {displayEntry.processingTimeMs != null ? ` (${displayEntry.processingTimeMs}ms)` : ''}
        </span>
      </div>
      {displayEntry.userRequest && (
        <CollapsibleSection title="Request" defaultOpen>
          <p className="assistant-output-history-detail__request">{displayEntry.userRequest}</p>
        </CollapsibleSection>
      )}
      {displayEntry.contextText && (
        <CollapsibleSection title="Context">
          <p className="assistant-output-history-detail__context">{displayEntry.contextText}</p>
        </CollapsibleSection>
      )}
      {latest.thinking && (
        <CollapsibleSection title="Thinking">
          <p className="assistant-output-history-detail__thinking">{latest.thinking}</p>
        </CollapsibleSection>
      )}
      <div
        className="assistant-output-history-detail__output-card"
        onMouseEnter={() => setHovering(true)}
        onMouseLeave={() => setHovering(false)}
      >
        <div className="assistant-output-history-detail__output-label">{outputLabel}</div>
        {isEditMode ? (
          <textarea
            className="assistant-output-history-detail__edit"
            value={editedContent}
            onChange={(event) => setEditedContent(event.target.value)}
          />
        ) : (
          <MarkdownView className="assistant-output-history-detail__output" content={latest.content} />
        )}
        {!isEditMode && (
          <div className={`assistant-output-history-detail__copy${hovering || copiedKind ? ' assistant-output-history-detail__copy--visible' : ''}`}>
            <button type="button" title="Copy rich text" onClick={() => copy('richText')}>
              <NativeSymbol name={copiedKind === 'richText' ? 'copied' : 'copyRich'} size={12} />
            </button>
            <button type="button" title="Copy markdown" onClick={() => copy('markdown')}>
              <NativeSymbol name={copiedKind === 'markdown' ? 'copied' : 'copyMarkdown'} size={12} />
            </button>
          </div>
        )}
      </div>
      {displayEntry.refinements.length > 0 && (
        <CollapsibleSection title="Original AssistantSession Output">
          <MarkdownView content={stripThinking(displayEntry.outputText)} />
        </CollapsibleSection>
      )}
      {displayEntry.explanationText && (
        <CollapsibleSection title="Explanation">
          <p>{displayEntry.explanationText}</p>
        </CollapsibleSection>
      )}
      {displayEntry.refinements.length > 0 && (
        <CollapsibleSection title={`Refinements (${displayEntry.refinements.length})`} defaultOpen>
          {displayEntry.refinements.map((refinement, index) => (
            // eslint-disable-next-line react/no-array-index-key
            <div key={`${refinement.timestamp}-${index}`} className="assistant-output-history-detail__refinement">
              <div className="assistant-output-history-detail__refinement-head">
                <strong>Refinement #{index + 1}</strong>
                <span>{formatRefinementTime(refinement.timestamp)}</span>
              </div>
              <p>{refinement.instruction}</p>
              <MarkdownView content={stripThinking(refinement.output)} />
            </div>
          ))}
        </CollapsibleSection>
      )}
      {actionError && <div className="assistant-output-history-detail__error">{actionError}</div>}
      <HistoryActionButtons
        isEditMode={isEditMode}
        sampleSaved={sampleSaved}
        savingSample={savingSample}
        onEnterEdit={() => {
          setEditedContent(displayEntry.outputText);
          setIsEditMode(true);
        }}
        onCancelEdit={() => {
          setIsEditMode(false);
          setEditedContent('');
        }}
        onApplyEdits={() => {
          setAppliedOutput(editedContent);
          setIsEditMode(false);
        }}
        onSaveAsSample={() => {
          const content = isEditMode && editedContent.trim().length > 0 ? editedContent : displayEntry.outputText;
          if (!content) return;
          setSavingSample(true);
          saveWritingSample(baseUrl, content, displayEntry.appName)
            .then(() => setSampleSaved(true))
            .catch(() => undefined)
            .finally(() => setSavingSample(false));
        }}
        onRefine={() => {
          if (displayEntry.outputType !== 'assistant_session') {
            setActionError('Legacy outputs can no longer be resumed.');
            return;
          }
          setActionError(null);
          onClearNativeActionError();
          refineFromHistory(displayEntry.id);
        }}
      />
    </div>
  );
}
