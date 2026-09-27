import {
  memo,
  useEffect,
  useState,
  type ClipboardEvent,
  type DragEvent,
  type RefObject,
} from 'react';
import type { ConversationVoiceCaptureState } from '../contracts';
import { MicrophoneIcon } from '@agent-task/components/sidebar/SidebarIcons';
import type { ReasoningModel } from '../services/api';
import ConversationModelPicker from './ConversationModelPicker';
import { StopAction } from '../../../shared/StopAction';
import RichTextComposer from '../../../shared/RichTextComposer';

interface ConversationComposerProps {
  editorRef: RefObject<HTMLDivElement>;
  responseError?: string;
  copyError?: string;
  attachmentError?: string;
  voiceError?: string;
  attachmentPaths: string[];
  processing: boolean;
  cancelling: boolean;
  voiceState: ConversationVoiceCaptureState;
  activeFormats: Record<string, boolean>;
  models: ReasoningModel[];
  selectedModelId?: string;
  delegationOptOut: boolean;
  onDelegationOptOutChange: (delegationOptOut: boolean) => void;
  sendDisabled: boolean;
  canRetryUnsent: boolean;
  canRestoreFailed: boolean;
  onRetryUnsent: () => void;
  onRestoreFailed: () => void;
  onRemoveAttachment: (path: string) => void;
  onExecuteCommand: (command: string, value?: string) => void;
  onToggleInlineCode: () => void;
  onDraftChange: (value: string) => void;
  onHtmlChange: (html: string) => void;
  onSubmit: () => void;
  onAttach: () => void;
  onModelChange: (modelId?: string) => void;
  onStartVoice: () => void;
  onStopVoice: () => void;
  onCancelVoice: () => void;
  onCancelResponse: () => void;
  onPasteImages: (files: File[]) => void;
  onArmFileDropTarget: () => void;
  onClearFileDropTarget: () => void;
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function voiceErrorMessage(error?: string): string | undefined {
  if (!error) return undefined;
  if (error === 'no_speech') return 'No speech was detected in the recording.';
  if (error === 'transcription_failed') return 'Transcription failed. Try again.';
  if (error === 'invalid_content_type') return 'The recorded audio format is invalid.';
  if (error === 'audio_too_small') return 'The recording was too short to transcribe.';
  return error;
}

function ConversationComposerComponent({
  editorRef,
  responseError,
  copyError,
  attachmentError,
  voiceError,
  attachmentPaths,
  processing,
  cancelling,
  voiceState,
  models,
  selectedModelId,
  delegationOptOut,
  onDelegationOptOutChange,
  sendDisabled,
  canRetryUnsent,
  canRestoreFailed,
  onRetryUnsent,
  onRestoreFailed,
  onRemoveAttachment,
  onDraftChange,
  onHtmlChange,
  onSubmit,
  onAttach,
  onModelChange,
  onStartVoice,
  onStopVoice,
  onCancelVoice,
  onCancelResponse,
  onPasteImages,
  onArmFileDropTarget,
  onClearFileDropTarget,
}: ConversationComposerProps) {
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const voiceBusy = voiceState === 'starting' || voiceState === 'recording' || voiceState === 'processing';
  const composerBusy = processing || voiceBusy;
  const voiceErrorText = voiceErrorMessage(voiceError);

  useEffect(() => () => {
    onClearFileDropTarget();
  }, [onClearFileDropTarget]);

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onArmFileDropTarget();
    setIsDraggingOver(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setIsDraggingOver(false);
    onClearFileDropTarget();
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingOver(false);
    onClearFileDropTarget();
  };

  const handlePaste = (event: ClipboardEvent<HTMLDivElement>) => {
    const imageFiles = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'));
    if (imageFiles.length === 0) return;
    event.preventDefault();
    onPasteImages(imageFiles);
  };

  return (
    <div
      className={`chats-composer-region${isDraggingOver ? ' is-drag-over' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDraggingOver ? (
        <div className="chats-composer-drop-overlay" aria-hidden="true">
          Drop files here
        </div>
      ) : null}
      {responseError ? (
        <div className="chats-response-error" role="alert">
          <span>{responseError}</span>
          {canRetryUnsent ? <button type="button" onClick={onRetryUnsent}>Retry</button> : null}
          {canRestoreFailed ? (
            <button type="button" onClick={onRestoreFailed}>
              Edit and send as a new turn
            </button>
          ) : null}
        </div>
      ) : null}
      {copyError ? <div className="chats-inline-error" role="alert">{copyError}</div> : null}
      {attachmentError ? <div className="chats-inline-error" role="alert">{attachmentError}</div> : null}
      {voiceErrorText ? <div className="chats-inline-error" role="alert">{voiceErrorText}</div> : null}
      {attachmentPaths.length > 0 ? (
        <div className="chats-pending-attachments" aria-label="Pending attachments">
          {attachmentPaths.map((path) => (
            <span key={path} title={path}>
              {basename(path)}
              <button
                type="button"
                onClick={() => onRemoveAttachment(path)}
                disabled={composerBusy}
                aria-label={`Remove ${basename(path)}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      ) : null}
      <RichTextComposer
        editorRef={editorRef}
        className="chats-composer"
        disabled={composerBusy}
        placeholder="Type your message here..."
        submitDisabled={sendDisabled || voiceBusy}
        onDraftChange={onDraftChange}
        onHtmlChange={onHtmlChange}
        onSubmit={onSubmit}
        onPaste={handlePaste}
        toolbarEnd={(
          <button
            type="button"
            className="chats-attach-button"
            onClick={onAttach}
            disabled={composerBusy}
            title="Attach files"
            aria-label="Attach files"
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
            </svg>
          </button>
        )}
        bottomStart={(
          <ConversationModelPicker
            models={models}
            selectedModelId={selectedModelId}
            disabled={composerBusy}
            onModelChange={onModelChange}
          />
        )}
        bottomMiddle={(
          <>
            <label className="chats-delegation-opt-out">
              <input
                type="checkbox"
                checked={delegationOptOut}
                disabled={composerBusy}
                onChange={(event) => onDelegationOptOutChange(event.target.checked)}
              />
              <span>Conversation only</span>
            </label>
            <button
              type="button"
              className="chats-delegation-help"
              aria-label="About Conversation only"
              title="Keeps this turn in Conversation. Agent Task tools, approvals, and progress are unavailable."
            >
              ?
            </button>
          </>
        )}
        bottomEnd={(
          <>
            <button
              type="button"
              className={`chats-voice-button toolbar-btn${voiceState === 'recording' || voiceState === 'starting' ? ' is-recording' : ''}`}
              onClick={() => {
                if (voiceState === 'idle' || voiceState === 'error') onStartVoice();
                else if (voiceState === 'starting' || voiceState === 'recording') onStopVoice();
              }}
              disabled={composerBusy && voiceState !== 'starting' && voiceState !== 'recording'}
              title={voiceState === 'processing' ? 'Transcribing' : voiceBusy ? 'Stop recording' : 'Voice input'}
              aria-label={voiceState === 'processing' ? 'Transcribing' : voiceBusy ? 'Stop recording' : 'Voice input'}
            >
              {voiceState === 'processing' ? 'Transcribing' : voiceBusy ? 'Stop' : <MicrophoneIcon size={13} />}
            </button>
            {voiceState === 'starting' || voiceState === 'recording' ? (
              <button type="button" className="chats-cancel-voice-button toolbar-btn" onClick={onCancelVoice}>Cancel</button>
            ) : null}
          </>
        )}
        sendReplacement={processing ? <StopAction isStopping={cancelling} onStop={onCancelResponse} /> : undefined}
      />
    </div>
  );
}

export default memo(ConversationComposerComponent);
