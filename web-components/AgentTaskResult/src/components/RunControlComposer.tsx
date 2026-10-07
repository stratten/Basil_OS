import { useEffect, useRef, useState } from 'react';
import * as api from '../services/api';
import { pickFiles, registerFilesPickedHandler } from '../services/bridge';
import { editorHtmlToDisplayMarkdown } from './request/requestMarkdown';
import FollowUpReferences from './FollowUpReferences';
import RichTextComposer from '../../../shared/RichTextComposer';

const MAX_NOTE_LENGTH = 4000;
const MAX_ATTACHMENTS = 20;

interface PendingNote {
  id: string;
  text: string;
  attachmentCount: number;
}

interface Props {
  turnTaskId: string;
  mode: 'running' | 'paused';
  deliveredNoteIds: ReadonlySet<string>;
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

/** The regular rich follow-up box, wired to steer a run that is still working or to resume one the user paused. */
export default function RunControlComposer({ turnTaskId, mode, deliveredNoteIds }: Props) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState('');
  const [pendingNotes, setPendingNotes] = useState<PendingNote[]>([]);
  const [busy, setBusy] = useState(false);
  const [pauseRequested, setPauseRequested] = useState(false);
  const [resumeRequested, setResumeRequested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [referencePaths, setReferencePaths] = useState<string[]>([]);

  useEffect(() => {
    setPauseRequested(false);
    setResumeRequested(false);
    setError(null);
  }, [mode, turnTaskId]);

  useEffect(() => {
    registerFilesPickedHandler((paths) => {
      setReferencePaths(previous => [...new Set([...previous, ...paths])].slice(0, MAX_ATTACHMENTS));
    });
    return () => registerFilesPickedHandler(() => {});
  }, []);

  const waitingNotes = pendingNotes.filter(pending => !deliveredNoteIds.has(pending.id));
  const hasNote = draft.trim().length > 0;

  const clearEditor = () => {
    if (editorRef.current) editorRef.current.innerHTML = '';
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
      await api.resumeSession(turnTaskId, note || undefined, referencePaths);
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
  const resumeTitle = hasNote || referencePaths.length > 0 ? 'Resume with your note (⌘↩)' : 'Resume (⌘↩)';
  const attachDisabled = busy || resumeRequested || referencePaths.length >= MAX_ATTACHMENTS;

  return (
    <div className={`text-followup run-control-composer is-${mode}`} data-run-control-mode={mode}>
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
        placeholder={isPaused ? 'Paused. Add a note if you like, then resume…' : 'Send Basil a note while it works…'}
        submitDisabled={isPaused ? busy || resumeRequested : busy || !hasNote}
        onDraftChange={setDraft}
        onSubmit={submit}
        toolbarEnd={(
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
        )}
        bottomStart={isPaused ? <span className="run-control-status" role="status">Paused</span> : undefined}
        bottomEnd={isPaused ? undefined : (
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
        )}
        sendReplacement={isPaused ? (
          <div className="rich-text-composer-send-control">
            <button
              type="button"
              className="rich-text-composer-send-button"
              onClick={() => void resume()}
              disabled={busy || resumeRequested}
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
      {error && <p className="run-control-error" role="alert">{error}</p>}
    </div>
  );
}
