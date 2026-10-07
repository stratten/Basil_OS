import { useCallback, useEffect, useRef, useState } from 'react';
import type { HomeVoiceCaptureState } from '../contracts';
import { editorHtmlToDisplayMarkdown } from '../../../shared/editorMarkdown';
import RichTextComposer from '../../../shared/RichTextComposer';
import { getReasoningModels, type ReasoningModel } from '../services/api';
import ConversationModelPicker from '../capabilities/ConversationModelPicker';
import {
  cancelHomeVoiceCapture,
  pickHomeFiles,
  registerHomeFilesPickedHandler,
  setBoardFileDropTarget,
  startHomeVoiceCapture,
  stopHomeVoiceCapture,
} from '../services/bridge';

export interface HomeComposerSubmission {
  content: string;
  displayMarkdown: string;
  referencePaths: string[];
  modelId?: string;
}

interface HomeComposerProps {
  disabled?: boolean;
  voiceState: HomeVoiceCaptureState;
  statusText?: string;
  onSubmit: (submission: HomeComposerSubmission) => Promise<void>;
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

export default function HomeComposer({ disabled = false, voiceState, statusText, onSubmit }: HomeComposerProps) {
  const [draftContent, setDraftContent] = useState('');
  const [referencePaths, setReferencePaths] = useState<string[]>([]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [availableModels, setAvailableModels] = useState<ReasoningModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  const recording = voiceState === 'recording' || voiceState === 'starting';
  const inputDisabled = disabled || submitting || voiceState === 'processing';

  useEffect(() => {
    editorRef.current?.focus();
  }, []);

  useEffect(() => () => {
    setBoardFileDropTarget();
  }, []);

  useEffect(() => {
    getReasoningModels()
      .then((data) => {
        setAvailableModels(data.models);
        setDefaultModelId(data.current_model);
        setSelectedModelId(data.current_model);
      })
      .catch((error) => console.error('[HomeComposer] Failed to load models:', error));
  }, []);

  useEffect(() => registerHomeFilesPickedHandler((paths) => {
    setReferencePaths((previous) => [...new Set([...previous, ...paths])]);
  }), []);

  const clearComposer = useCallback(() => {
    if (editorRef.current) editorRef.current.innerHTML = '';
    setDraftContent('');
    setReferencePaths([]);
  }, []);

  const submit = useCallback(async () => {
    const content = editorRef.current?.innerText.trim() ?? '';
    if (!content || inputDisabled) return;
    const modelId = selectedModelId && selectedModelId !== defaultModelId ? selectedModelId : undefined;
    setSubmitting(true);
    try {
      await onSubmit({
        content,
        displayMarkdown: editorRef.current ? editorHtmlToDisplayMarkdown(editorRef.current) : '',
        referencePaths,
        modelId,
      });
      clearComposer();
    } catch (error) {
      console.error('[HomeComposer] Submit failed:', error);
    } finally {
      setSubmitting(false);
    }
  }, [clearComposer, defaultModelId, inputDisabled, onSubmit, referencePaths, selectedModelId]);

  function handleDragOver(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setBoardFileDropTarget('home');
    setIsDraggingOver(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>): void {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setBoardFileDropTarget();
    setIsDraggingOver(false);
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setBoardFileDropTarget();
    setIsDraggingOver(false);
  }

  const sendDisabled = inputDisabled || !draftContent.trim();

  return (
    <div className="home-composer">
      <div
        className={`home-composer-shell text-followup${isDraggingOver ? ' is-drag-over' : ''}`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        {isDraggingOver ? (
          <div className="home-composer-drop-overlay" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="var(--secondary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
              <path d="M8 10V2M5 5l3-3 3 3" />
              <path d="M2 10v3a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3" />
            </svg>
            <span>Drop files here</span>
          </div>
        ) : null}
        <RichTextComposer
          editorRef={editorRef}
          className="home-composer-editor-shell"
          editorClassName="home-composer-editor"
          disabled={inputDisabled}
          placeholder="Ask a question, or describe what you need done..."
          submitDisabled={sendDisabled}
          onDraftChange={setDraftContent}
          onSubmit={() => void submit()}
          toolbarEnd={(
            <button
              type="button"
              onClick={() => pickHomeFiles()}
              disabled={inputDisabled}
              title="Attach files or folders"
              aria-label="Attach files or folders"
              className="text-followup-action-btn home-composer-attach"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
              </svg>
            </button>
          )}
          bottomStart={(
            <ConversationModelPicker
              models={availableModels}
              selectedModelId={selectedModelId ?? undefined}
              disabled={inputDisabled}
              onModelChange={(modelId) => setSelectedModelId(modelId ?? null)}
            />
          )}
          bottomEnd={(
            <>
              <button
                type="button"
                className={`home-voice-button text-followup-action-btn${recording ? ' is-recording' : ''}`}
                onClick={() => (recording ? stopHomeVoiceCapture() : startHomeVoiceCapture())}
                disabled={inputDisabled}
                title={recording ? 'Stop voice capture' : 'Start voice capture'}
                aria-label={recording ? 'Stop voice capture' : 'Start voice capture'}
              >
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <rect x="5.5" y="1" width="5" height="8" rx="2.5" />
                  <path d="M3.5 7a4.5 4.5 0 0 0 9 0" />
                  <line x1="8" y1="11.5" x2="8" y2="14" />
                  <line x1="5.5" y1="14" x2="10.5" y2="14" />
                </svg>
              </button>
              {recording ? <button type="button" className="home-cancel-button text-followup-action-btn" onClick={() => cancelHomeVoiceCapture()}>Cancel</button> : null}
            </>
          )}
        />
        {statusText ? (
          <div className="home-composer-status" role="status">
            <span className="home-composer-status-dot" aria-hidden="true" />
            {statusText}
          </div>
        ) : null}
        {referencePaths.length > 0 ? (
          <div className="home-composer-references">
            <div className="home-composer-references-label">
              <svg width="9" height="9" viewBox="0 0 16 16" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
              </svg>
              <span>References</span>
            </div>
            {referencePaths.map((path, index) => (
              <div key={`${path}-${index}`} className="home-composer-reference-row">
                <svg width="9" height="9" viewBox="0 0 14 16" fill="rgba(0,48,135,0.7)" aria-hidden="true">
                  <path d="M8 0H3a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 3 16h8a1.5 1.5 0 0 0 1.5-1.5V5L8 0z" />
                </svg>
                <span className="home-composer-reference-name" title={path}>{basename(path)}</span>
                <button
                  type="button"
                  className="home-composer-reference-remove"
                  onClick={() => setReferencePaths((previous) => previous.filter((_, itemIndex) => itemIndex !== index))}
                  aria-label={`Remove ${basename(path)}`}
                >
                  <svg width="10" height="10" viewBox="0 0 16 16" fill="var(--text-tertiary)" opacity="0.6" aria-hidden="true">
                    <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm2.12 4.88a.75.75 0 0 0-1.06 0L8 5.94 6.94 4.88a.75.75 0 1 0-1.06 1.06L6.94 7 5.88 8.06a.75.75 0 1 0 1.06 1.06L8 8.06l1.06 1.06a.75.75 0 0 0 1.06-1.06L9.06 7l1.06-1.06a.75.75 0 0 0 0-1.06z" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
