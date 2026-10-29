import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import { pickFiles, registerFilesPickedHandler } from '../services/bridge';
import { editorHtmlToDisplayMarkdown } from './request/requestMarkdown';
import FollowUpReferences from './FollowUpReferences';
import RichTextComposer from '../../../shared/RichTextComposer';
import AttachmentDropZone from '../../../shared/AttachmentDropZone';
import CollapsibleRegion from '../../../shared/CollapsibleRegion';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';
import { useFollowUpComposerCollapsed } from '../store/followUpComposerViewStore';
import {
  forgetComposerDraft,
  loadComposerDraft,
  moveComposerDraft,
  rememberComposerHtml,
  rememberComposerReferences,
} from '../store/composerDraftStore';

const MAX_NOTE_LENGTH = 4000;
const MAX_ATTACHMENTS = 20;
const COLLAPSED_DRAFT_PREVIEW_CHARS = 80;

interface PendingNote {
  id: string;
  text: string;
  attachmentCount: number;
}

interface Props {
  turnTaskId: string;
  /** The chain this turn belongs to. The fold state is kept per chain, shared with the follow-up box that replaces this one when the run finishes, so a folded box stays folded. Falls back to the turn when absent. */
  rootTaskId?: string;
  mode: 'running' | 'paused';
  deliveredNoteIds: ReadonlySet<string>;
  /** The run paused because Basil lost its connection to the model, not because you paused it. */
  connectionLost?: boolean;
}

function plainError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : '';
  return message.replace(/\s*\(\d{3}\)$/, '').trim() || fallback;
}

function readNote(editor: HTMLDivElement | null): string {
  if (!editor) return '';
  const plain = editor.innerText.trim();
  if (!plain) return '';
  return editorHtmlToDisplayMarkdown(editor).trim() || plain;
}

function PauseGlyph() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <rect x="3.5" y="2.5" width="3" height="11" rx="0.75" />
      <rect x="9.5" y="2.5" width="3" height="11" rx="0.75" />
    </svg>
  );
}

function AttachGlyph() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
    </svg>
  );
}

function ResumeGlyph() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M4.5 2.6v10.8a.6.6 0 0 0 .92.5l8.4-5.4a.6.6 0 0 0 0-1L5.42 2.1a.6.6 0 0 0-.92.5Z" />
    </svg>
  );
}

/** The regular rich follow-up box, wired to steer a run that is still working or to resume one that is paused. */
export default function RunControlComposer({ turnTaskId, rootTaskId, mode, deliveredNoteIds, connectionLost = false }: Props) {
  const editorRef = useRef<HTMLDivElement>(null);
  const draftKey = rootTaskId || turnTaskId;
  const [folded, setFolded] = useFollowUpComposerCollapsed(draftKey);
  // Only a running box folds. Paused, the box carries the Resume control and the note for resuming, so it always opens.
  const collapsed = folded && mode === 'running';
  const bodyId = useId();
  const barRef = useRef<HTMLButtonElement>(null);
  const wasFoldedRef = useRef(folded);
  const [draft, setDraft] = useState('');
  const [pendingNotes, setPendingNotes] = useState<PendingNote[]>([]);
  const [busy, setBusy] = useState(false);
  const [pauseRequested, setPauseRequested] = useState(false);
  const [resumeRequested, setResumeRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // An unsent note comes back with the box. It unmounts when an approval or checkpoint prompt takes its place and when its task is switched away from, and a fresh one starts empty.
  const [referencePaths, setReferencePaths] = useState<string[]>(
    () => loadComposerDraft('note', draftKey)?.referencePaths ?? [],
  );
  const [switching, setSwitching] = useState(false);
  const [switchModelId, setSwitchModelId] = useState<string | undefined>(undefined);
  const [models, setModels] = useState<api.ReasoningModel[]>([]);

  useEffect(() => {
    setPauseRequested(false);
    setResumeRequested(false);
    setError(null);
    setSwitching(false);
    setSwitchModelId(undefined);
  }, [mode, turnTaskId, connectionLost]);

  // Continuing with another model is an explicit choice, so the list is only fetched once the user asks for it.
  useEffect(() => {
    if (!switching || models.length > 0) return undefined;
    let canceled = false;
    api.getReasoningModels()
      .then(data => {
        if (!canceled) setModels(data.models);
      })
      .catch(() => {
        if (!canceled) setError('Basil could not load the list of models.');
      });
    return () => {
      canceled = true;
    };
  }, [switching, models.length]);

  useEffect(() => registerFilesPickedHandler((paths) => {
    setReferencePaths(previous => [...new Set([...previous, ...paths])].slice(0, MAX_ATTACHMENTS));
  }), []);

  // Follows the reader's own fold and unfold only. A run pausing unfolds the box by itself and must not pull focus into it. The fold control sits inside the region that just became inert, so focus moves to the bar that replaces it.
  useEffect(() => {
    if (wasFoldedRef.current && !folded) editorRef.current?.focus();
    if (!wasFoldedRef.current && folded && mode === 'running') barRef.current?.focus();
    wasFoldedRef.current = folded;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folded]);

  // Put the saved text back before the first paint.
  useLayoutEffect(() => {
    const editor = editorRef.current;
    const saved = loadComposerDraft('note', draftKey);
    if (!editor || !saved?.html) return;
    editor.innerHTML = saved.html;
    setDraft((editor.innerText ?? editor.textContent ?? '').trim());
    // Mount only: later key changes are handled by the move below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The same chain can start to be identified differently while the box stays open. The draft goes with it instead of staying behind under the old key.
  const draftKeyRef = useRef(draftKey);
  useEffect(() => {
    if (draftKeyRef.current === draftKey) return;
    moveComposerDraft('note', draftKeyRef.current, draftKey);
    draftKeyRef.current = draftKey;
  }, [draftKey]);

  useEffect(() => {
    rememberComposerReferences('note', draftKey, referencePaths);
  }, [referencePaths, draftKey]);

  const rememberDraftHtml = useCallback((html: string) => {
    const editor = editorRef.current;
    const hasText = (editor?.innerText ?? editor?.textContent ?? '').trim() !== '';
    rememberComposerHtml('note', draftKey, html, hasText);
  }, [draftKey]);

  const waitingNotes = pendingNotes.filter(pending => !deliveredNoteIds.has(pending.id));
  const hasNote = draft.trim().length > 0;

  const clearEditor = () => {
    if (editorRef.current) editorRef.current.innerHTML = '';
    forgetComposerDraft('note', draftKey);
    setDraft('');
    setReferencePaths([]);
  };

  const sendNote = async () => {
    const note = readNote(editorRef.current);
    if (!note || busy) return;
    if (note.length > MAX_NOTE_LENGTH) {
      setError(`Notes can be up to ${MAX_NOTE_LENGTH.toLocaleString('en-US')} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.sendRunMessage(turnTaskId, note, referencePaths);
      const attachmentCount = referencePaths.length;
      setPendingNotes(current => [
        ...current,
        { id: response.message_id || `local_${current.length}`, text: note, attachmentCount },
      ]);
      clearEditor();
    } catch (sendError) {
      setError(plainError(sendError, 'Basil could not take your note.'));
    } finally {
      setBusy(false);
    }
  };

  const pause = async () => {
    if (busy || pauseRequested) return;
    setBusy(true);
    setError(null);
    try {
      await api.pauseSession(turnTaskId);
      setPauseRequested(true);
    } catch (pauseError) {
      setError(plainError(pauseError, 'Basil could not pause.'));
    } finally {
      setBusy(false);
    }
  };

  const resume = async () => {
    if (busy || resumeRequested) return;
    const note = readNote(editorRef.current);
    if (note.length > MAX_NOTE_LENGTH) {
      setError(`Notes can be up to ${MAX_NOTE_LENGTH.toLocaleString('en-US')} characters.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const modelId = connectionLost && switching ? switchModelId : undefined;
      if (modelId) await api.resumeSession(turnTaskId, note || undefined, referencePaths, modelId);
      else await api.resumeSession(turnTaskId, note || undefined, referencePaths);
      setResumeRequested(true);
      clearEditor();
    } catch (resumeError) {
      setError(plainError(resumeError, 'Basil could not resume.'));
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    if (mode === 'paused') void resume();
    else void sendNote();
  };

  const isPaused = mode === 'paused';
  const needsModelChoice = connectionLost && switching && !switchModelId;
  const resumeTitle = needsModelChoice
    ? 'Choose a model to continue with'
    : hasNote || referencePaths.length > 0 ? 'Resume with your note (⌘↩)' : 'Resume (⌘↩)';
  const pausedPlaceholder = connectionLost
    ? 'Basil lost its connection. Your progress is saved. Add a note if you like, then resume…'
    : 'Paused. Add a note if you like, then resume…';
  const attachDisabled = busy || resumeRequested || referencePaths.length >= MAX_ATTACHMENTS;
  const draftPreview = draft.trim().replace(/\s+/g, ' ');
  const draftPreviewText = draftPreview.length > COLLAPSED_DRAFT_PREVIEW_CHARS
    ? `${draftPreview.slice(0, COLLAPSED_DRAFT_PREVIEW_CHARS)}...`
    : draftPreview;

  // The same control lives in the box's bottom row and, folded, under the bar, so a run can always be paused.
  const pauseButton = (
    <button
      type="button"
      className={`text-followup-action-btn run-control-pause${pauseRequested ? ' is-pending' : ''}`}
      onClick={() => void pause()}
      disabled={pauseRequested || busy}
      title={pauseRequested ? 'Pausing after this step' : 'Pause after the current step'}
      aria-label={pauseRequested ? 'Pausing after this step' : 'Pause'}
    >
      <PauseGlyph />
    </button>
  );

  return (
    <div className="text-followup-collapsible run-control-collapsible">
      {/* The bar exists only while folded. Open, the box is just the text area and the fold arrow rides in its toolbar. Pause stays under the bar so the run can still be paused. */}
      {collapsed && (
        <>
          <button
            ref={barRef}
            type="button"
            className="text-followup-bar"
            aria-expanded={false}
            aria-controls={bodyId}
            aria-label="Open the note box"
            onClick={() => setFolded(false)}
          >
            <ExecutionDisclosureChevron expanded={false} color="var(--text-primary)" />
            <span className="text-followup-bar-title">Note for Basil</span>
            {draftPreviewText !== '' && <span className="text-followup-bar-draft">Draft: {draftPreviewText}</span>}
          </button>
          <div className="run-control-collapsed-actions">{pauseButton}</div>
        </>
      )}
      <CollapsibleRegion expanded={!collapsed} id={bodyId}>
        <div className="text-followup-collapsible-body">
            <AttachmentDropZone className={`text-followup run-control-composer is-${mode}`} data-run-control-mode={mode} disabled={attachDisabled}>
              {waitingNotes.length > 0 && (
                <ul className="run-control-queued" aria-label="Notes waiting for Basil">
                  {waitingNotes.map(pending => (
                    <li key={pending.id} title={pending.text}>
                      <span className="run-control-queued-label">Queued</span>
                      <span className="run-control-queued-text">{pending.text}</span>
                      {pending.attachmentCount > 0 && (
                        <span className="run-control-queued-files">
                          {pending.attachmentCount === 1 ? '1 file' : `${pending.attachmentCount} files`}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <RichTextComposer
                editorRef={editorRef}
                editorClassName="text-followup-editor"
                editorAriaLabel={isPaused ? 'Note for when Basil resumes' : 'Note for Basil'}
                disabled={resumeRequested}
                placeholder={isPaused ? pausedPlaceholder : 'Send Basil a note while it works…'}
                submitDisabled={isPaused ? busy || resumeRequested || needsModelChoice : busy || !hasNote}
                onDraftChange={setDraft}
                onHtmlChange={rememberDraftHtml}
                onSubmit={submit}
                toolbarEnd={(
                  <>
                    <button
                      type="button"
                      className="text-followup-action-btn"
                      onClick={() => pickFiles()}
                      disabled={attachDisabled}
                      title="Attach files or folders"
                      aria-label="Attach files or folders"
                    >
                      <AttachGlyph />
                    </button>
                    {!isPaused && (
                      <button
                        type="button"
                        className="text-followup-action-btn text-followup-collapse-btn"
                        aria-expanded
                        aria-controls={bodyId}
                        onClick={() => setFolded(true)}
                        title="Collapse the note box"
                        aria-label="Collapse the note box"
                      >
                        <ExecutionDisclosureChevron expanded color="currentColor" />
                      </button>
                    )}
                  </>
                )}
                bottomStart={isPaused ? (
                  <>
                    <span className={`run-control-status${connectionLost ? ' run-control-status--connection-lost' : ''}`} role="status">{connectionLost ? 'Connection lost' : 'Paused'}</span>
                    {connectionLost && (
                      <button
                        type="button"
                        className="run-control-switch-toggle"
                        aria-pressed={switching}
                        disabled={busy || resumeRequested}
                        onClick={() => {
                          setSwitching(current => !current);
                          setSwitchModelId(undefined);
                        }}
                      >
                        {switching ? 'Use the same model' : 'Continue with a different model…'}
                      </button>
                    )}
                  </>
                ) : undefined}
                bottomEnd={isPaused ? (connectionLost && switching ? (
                  <ReasoningModelPicker
                    models={models}
                    selectedModelId={switchModelId}
                    disabled={busy || resumeRequested}
                    onModelChange={setSwitchModelId}
                    ariaLabel="Model to continue with"
                    placeholder="Choose model"
                  />
                ) : undefined) : pauseButton}
                sendReplacement={isPaused ? (
                  <div className="rich-text-composer-send-control">
                    <button
                      type="button"
                      className="rich-text-composer-send-button"
                      onClick={() => void resume()}
                      disabled={busy || resumeRequested || needsModelChoice}
                      title={resumeTitle}
                      aria-label="Resume"
                    >
                      <ResumeGlyph />
                    </button>
                    <span className="rich-text-composer-send-shortcut chats-send-shortcut" title="Command-Return resumes" aria-label="Command-Return resumes">
                      <span>⌘</span>
                      <span>↩</span>
                    </span>
                  </div>
                ) : undefined}
              />
              <FollowUpReferences
                paths={referencePaths}
                onRemove={(index) => setReferencePaths(previous => previous.filter((_, itemIndex) => itemIndex !== index))}
              />
              {connectionLost && switching && (
                <p className="run-control-switch-note">
                  Basil carries your saved progress into a new, more limited run with the model you choose. The model is not
                  swapped inside the interrupted run, and Basil will check the current state before repeating anything.
                </p>
              )}
              {error && <p className="run-control-error" role="alert">{error}</p>}
            </AttachmentDropZone>
        </div>
      </CollapsibleRegion>
    </div>
  );
}
