// web-components/TranscriptionWidget/src/app/AudioFileUploadApp.tsx

import { useEffect, useReducer } from 'react';
import TokenizedSelect from '@shared/TokenizedSelect';
import { BasilWindowChrome } from '@shared/BasilWindowChrome';
import {
  cancelAudioUpload,
  clearSelectedFile,
  collapseAudioUpload,
  copyTranscriptionResult,
  dismissAudioUploadError,
  expandAudioUpload,
  minimizeAudioUpload,
  onAudioFileUploadEvent,
  reportAudioUploadReady,
  selectAudioFile,
  setDescription,
  setLanguage,
  uploadAudioFile,
} from '../bridge/audioFileUploadBridge';
import { applyAudioFileUploadEvent, initialAudioFileUploadState, resolveAudioUploadTheme } from '../state/audioFileUploadReducer';
import { AUDIO_UPLOAD_LANGUAGE_OPTIONS } from '../bridge/audioFileUploadTypes';
import { TranscriptionSymbol } from '../components/TranscriptionSymbol';
import { applyHostFonts, applyHostTheme } from '@shared/webTheme';

export function AudioFileUploadApp() {
  const [state, dispatch] = useReducer(applyAudioFileUploadEvent, initialAudioFileUploadState);

  useEffect(() => {
    const unsubscribe = onAudioFileUploadEvent(dispatch);
    reportAudioUploadReady();
    return unsubscribe;
  }, []);

  const theme = resolveAudioUploadTheme(state);
  useEffect(() => {
    applyHostTheme(theme);
    applyHostFonts(theme.fonts);
  }, [theme]);

  return (
    <BasilWindowChrome
      title="Upload Audio File"
      onClose={() => cancelAudioUpload()}
      onMinimize={() => minimizeAudioUpload()}
      onCollapse={() => collapseAudioUpload()}
      onExpand={() => expandAudioUpload()}
    >
      <div className="audio-upload-root">
        <div className="audio-upload-body">
        <div className="audio-upload-file-info">
        {state.hasSelectedFile ? (
          <div className="audio-upload-file-info__selected">
            <span className="audio-upload-file-info__icon"><TranscriptionSymbol name="waveform" size={28} /></span>
            <div className="audio-upload-file-info__details">
              <p className="audio-upload-file-info__name">{state.selectedFileName}</p>
              {state.fileSizeDisplay ? <p className="audio-upload-file-info__meta">{state.fileSizeDisplay}</p> : null}
              {state.fileDurationDisplay ? <p className="audio-upload-file-info__meta">{state.fileDurationDisplay}</p> : null}
            </div>
            <button type="button" className="audio-upload-file-info__clear" onClick={() => clearSelectedFile()} aria-label="Remove selected file">
              ✕
            </button>
          </div>
        ) : (
          <button type="button" className="audio-upload-file-info__empty" onClick={() => selectAudioFile()}>
            <span className="audio-upload-file-info__icon"><TranscriptionSymbol name="uploadDoc" size={36} /></span>
            <span>Click to select an audio file</span>
          </button>
        )}
      </div>

      <div className="audio-upload-form">
        <label className="audio-upload-form__field">
          <span>Description (optional)</span>
          <textarea
            value={state.description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Add a description or notes about this audio file"
            rows={3}
          />
        </label>
        <label className="audio-upload-form__field">
          <span>Language</span>
          <TokenizedSelect
            value={state.selectedLanguage}
            ariaLabel="Language"
            onValueChange={setLanguage}
            options={AUDIO_UPLOAD_LANGUAGE_OPTIONS.map((option) => ({ value: option.value, label: option.label }))}
          />
        </label>
      </div>

      <div className="audio-upload-actions">
        <button type="button" className="audio-upload-actions__cancel" onClick={() => cancelAudioUpload()}>
          Cancel
        </button>
        <div className="audio-upload-actions__spacer" />
        <button type="button" className="audio-upload-actions__select" onClick={() => selectAudioFile()} disabled={state.isUploading}>
          Select Audio File
        </button>
        <button
          type="button"
          className="audio-upload-actions__upload"
          onClick={() => uploadAudioFile()}
          disabled={!state.canUpload || state.isUploading}
        >
          Upload and Transcribe
        </button>
      </div>

      {state.isUploading ? (
        <div className="audio-upload-progress">
          <div className="audio-upload-progress__spinner" aria-hidden="true" />
          <p>{state.uploadStatus}</p>
        </div>
      ) : null}

      {state.transcriptionResult ? (
        <div className="audio-upload-result">
          <div className="audio-upload-result__header">
            <h2>Transcription Result</h2>
            <button type="button" onClick={() => copyTranscriptionResult()}>
              Copy
            </button>
          </div>
          <div className="audio-upload-result__body">{state.transcriptionResult}</div>
        </div>
      ) : null}

      {state.errorMessage ? (
        <div className="audio-upload-error" role="alert">
          <p>{state.errorMessage}</p>
          <button type="button" onClick={() => dismissAudioUploadError()}>
            Dismiss
          </button>
        </div>
      ) : null}
      </div>
      </div>
    </BasilWindowChrome>
  );
}
