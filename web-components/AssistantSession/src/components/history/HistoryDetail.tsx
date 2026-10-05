import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { CollapsibleSection } from './CollapsibleSection';
import { HistoryActionButtons, type HistorySampleStatus } from './ActionButtons';
import { MarkdownView } from '../MarkdownView';
import { formatDetailTimestamp, formatRefinementTime } from '../../lib/historyTimestamps';
import { splitThinking, stripThinking } from '../../lib/thinkingExtractor';
import {
  AssistantOutputHistoryApiError,
  SAMPLE_CONTEXT_OPTIONS,
  saveHistoryOutputAsSample,
  updateSavedSampleContent,
  type AssistantOutputHistoryDetail,
  type SampleContextType,
  type SavedHistorySample,
} from '../../services/historyApi';
import { copyHistoryMarkdown, copyHistoryRichText, refineFromHistory } from '../../bridge/historyBridge';
import { NativeSymbol } from '../NativeSymbol';

const EDIT_MIN_HEIGHT_PX = 120;
const EDIT_CHROME_ALLOWANCE_PX = 72;

function defaultSampleContext(appName: string | null | undefined): SampleContextType {
  const normalized = (appName ?? '').toLowerCase();
  return normalized.includes('mail') || normalized.includes('outlook') ? 'email_reply' : 'document';
}

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
  const [savedSample, setSavedSample] = useState<SavedHistorySample | null>(null);
  const [sampleContext, setSampleContext] = useState<SampleContextType>('document');
  const [savingSample, setSavingSample] = useState(false);
  const [hovering, setHovering] = useState(false);
  const [copiedKind, setCopiedKind] = useState<'richText' | 'markdown' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const editRef = useRef<HTMLTextAreaElement>(null);
  const activeEntryIdRef = useRef<number | null>(null);
  activeEntryIdRef.current = entry?.id ?? null;

  useEffect(() => {
    setIsEditMode(false);
    setEditedContent('');
    setAppliedOutput(null);
    setSavedSample(entry?.savedSample ?? null);
    setSampleContext(defaultSampleContext(entry?.appName));
    setSavingSample(false);
    setActionError(null);
  }, [entry?.id]);

  useEffect(() => {
    if (nativeActionError) setActionError(nativeActionError);
  }, [nativeActionError]);

  useLayoutEffect(() => {
    const textarea = editRef.current;
    if (!isEditMode || !textarea) return undefined;
    const fit = () => {
      const pane = textarea.closest<HTMLElement>('.assistant-output-history-detail');
      const actions = pane?.querySelector<HTMLElement>('.assistant-output-history-detail__actions');
      const available = pane && pane.clientHeight > 0
        ? pane.clientHeight - (actions?.offsetHeight ?? 0) - EDIT_CHROME_ALLOWANCE_PX
        : Number.POSITIVE_INFINITY;
      textarea.style.height = 'auto';
      const target = Math.max(EDIT_MIN_HEIGHT_PX, Math.min(textarea.scrollHeight + 4, available));
      textarea.style.height = `${target}px`;
    };
    fit();
    window.addEventListener('resize', fit);
    return () => window.removeEventListener('resize', fit);
  }, [isEditMode, editedContent]);

  useEffect(() => {
    if (isEditMode) editRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [isEditMode]);

  if (loading) {
    return (
      <div className="assistant-output-history-detail assistant-output-history-detail--empty">
        Loading output...
      </div>
    );
  }

  if (!entry) {
    return (
      <div className="assistant-output-history-detail assistant-output-history-detail--empty">
        Select an output to view details
      </div>
    );
  }

  const latestRaw = entry.refinements[entry.refinements.length - 1]?.output ?? entry.outputText;
  const latest = splitThinking(latestRaw);
  const currentOutput = appliedOutput ?? latest.content;
  const sampleContent = isEditMode ? editedContent : currentOutput;
  const sampleStatus: HistorySampleStatus = savedSample == null
    ? 'unsaved'
    : savedSample.content === sampleContent ? 'saved' : 'changed';
  const outputLabel = entry.refinements.length > 0
    ? `Latest (Refinement #${entry.refinements.length})`
    : 'Output';

  const flash = (kind: 'richText' | 'markdown') => {
    setCopiedKind(kind);
    window.setTimeout(() => {
      setCopiedKind((current) => (current === kind ? null : current));
    }, 1500);
  };

  const copy = (kind: 'richText' | 'markdown') => {
    if (kind === 'richText') {
      copyHistoryRichText(currentOutput);
    } else {
      copyHistoryMarkdown(currentOutput);
    }
    flash(kind);
  };

  const saveSample = () => {
    if (!sampleContent.trim() || savingSample) return;
    const entryId = entry.id;
    const existing = savedSample;
    setSavingSample(true);
    setActionError(null);
    const request = existing
      ? updateSavedSampleContent(baseUrl, existing.id, sampleContent)
      : saveHistoryOutputAsSample(baseUrl, entryId, sampleContent, entry.sampleContextType ? null : sampleContext);
    request
      .then((sample) => {
        if (activeEntryIdRef.current === entryId) setSavedSample(sample);
      })
      .catch((error: unknown) => {
        if (activeEntryIdRef.current !== entryId) return;
        if (existing && error instanceof AssistantOutputHistoryApiError && error.status === 404) {
          setSavedSample(null);
          setActionError('The saved sample no longer exists. Save it again to create a new sample.');
          return;
        }
        setActionError(existing ? 'Failed to update the saved sample.' : 'Failed to save sample.');
      })
      .finally(() => {
        if (activeEntryIdRef.current === entryId) setSavingSample(false);
      });
  };

  return (
    <div className="assistant-output-history-detail">
      <div className="assistant-output-history-detail__header">
        <span className="assistant-output-history-detail__badge">
          Dill{entry.inputModality ? ` · ${entry.inputModality}` : ''}
        </span>
        {entry.appName && <span className="assistant-output-history-detail__app">in {entry.appName}</span>}
        <span className="assistant-output-history-detail__time">
          {formatDetailTimestamp(entry.timestamp)}
          {entry.processingTimeMs != null ? ` (${entry.processingTimeMs}ms)` : ''}
        </span>
      </div>
      {entry.userRequest && (
        <CollapsibleSection title="Request" defaultOpen>
          <p className="assistant-output-history-detail__request">{entry.userRequest}</p>
        </CollapsibleSection>
      )}
      {entry.contextText && (
        <CollapsibleSection title="Context">
          <p className="assistant-output-history-detail__context">{entry.contextText}</p>
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
            ref={editRef}
            className="assistant-output-history-detail__edit"
            aria-label="Edit output"
            value={editedContent}
            onChange={(event) => setEditedContent(event.target.value)}
          />
        ) : (
          <MarkdownView className="assistant-output-history-detail__output" content={currentOutput} />
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
      {entry.refinements.length > 0 && (
        <CollapsibleSection title="Original output">
          <MarkdownView content={stripThinking(entry.outputText)} />
        </CollapsibleSection>
      )}
      {entry.explanationText && (
        <CollapsibleSection title="Explanation">
          <p>{entry.explanationText}</p>
        </CollapsibleSection>
      )}
      {entry.refinements.length > 0 && (
        <CollapsibleSection title={`Refinements (${entry.refinements.length})`} defaultOpen>
          {entry.refinements.map((refinement, index) => (
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
        sampleStatus={sampleStatus}
        savingSample={savingSample}
        contextPicker={entry.sampleContextType ? null : {
          value: sampleContext,
          options: SAMPLE_CONTEXT_OPTIONS,
          onChange: setSampleContext,
        }}
        onEnterEdit={() => {
          setEditedContent(currentOutput);
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
        onSaveAsSample={saveSample}
        onRefine={(input) => {
          if (entry.outputType !== 'assistant_session') {
            setActionError('Legacy outputs can no longer be resumed.');
            return;
          }
          setActionError(null);
          onClearNativeActionError();
          refineFromHistory(entry.id, input);
        }}
      />
    </div>
  );
}
