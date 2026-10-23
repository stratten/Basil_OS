// web-components/TranscriptionWidget/src/components/FullWidget.tsx

import { memo } from 'react';
import { clearTranscription, closeWidget, openSystemMicrophoneSettings, toggleMinimizedState, toggleRecording } from '../bridge/transcriptionWidgetBridge';
import { TranscriptionAudioBubble } from './TranscriptionAudioBubble';
import { TimerDisplay } from './TimerDisplay';
import { TranscriptionModelPickerMenu } from './TranscriptionModelPickerMenu';
import { TranscriptBody } from './TranscriptBody';
import { TranscriptionSymbol } from './TranscriptionSymbol';
import type { TranscriptionState } from '../state/transcriptionReducer';
import { resolveDisplayText, isStatusMessage } from '../lib/widgetPhase';

const MIC_PERMISSION_LINK_MARKER = 'Click here to open System Settings';

export const FullWidget = memo(function FullWidget({ state }: { state: TranscriptionState }) {
  const displayText = resolveDisplayText(state);
  const statusMessage = isStatusMessage(displayText);
  const showMicPermissionLink = Boolean(state.error?.includes(MIC_PERMISSION_LINK_MARKER));

  function handleCloseClick(): void {
    closeWidget();
  }

  return (
    <div className="transcription-widget transcription-widget--full">
      <div className="transcription-widget__header">
        <div className="transcription-widget__header-left">
          <button type="button" className="transcription-widget__icon-button transcription-widget__icon-button--close" aria-label="Close" onClick={handleCloseClick}>
            <TranscriptionSymbol name="close" size={18} />
          </button>
          <button type="button" className="transcription-widget__icon-button" aria-label="Minimize widget" onClick={() => toggleMinimizedState()}>
            <TranscriptionSymbol name="minimize" size={13} />
          </button>
          <span className="transcription-widget__mic-icon"><TranscriptionSymbol name="micFill" size={16} /></span>
          <span className="transcription-widget__title">Transcription</span>
        </div>
        <div className="transcription-widget__header-right">
          <TranscriptionAudioBubble size={50} bubbleMode={state.bubbleMode} bubbleColors={state.bubbleColors} />
        </div>
      </div>

      <TranscriptBody displayText={displayText} isStatus={statusMessage} />

      <div className="transcription-widget__status-messages">
        {!state.isConnected ? <p className="transcription-widget__status-error">Disconnected from server</p> : null}
        {state.error ? (
          showMicPermissionLink ? (
            <button type="button" className="transcription-widget__status-link" onClick={() => openSystemMicrophoneSettings()}>
              {state.error}
            </button>
          ) : (
            <p className="transcription-widget__status-error">{state.error}</p>
          )
        ) : null}
      </div>

      <div className="transcription-widget__button-row">
        <TranscriptionModelPickerMenu state={state} style="fullLabel" />
        <div className="transcription-widget__spacer" />
        {state.isRecording ? <TimerDisplay seconds={state.elapsedSeconds} /> : null}
        <button
          type="button"
          className="transcription-widget__primary-button transcription-widget__primary-button--record"
          disabled={!state.canToggleRecording}
          onClick={() => toggleRecording()}
        >
          <TranscriptionSymbol name={state.isStartingRecording ? 'closeFill' : state.isRecording ? 'stop' : 'record'} size={12} />
          <span>{state.isStartingRecording ? 'Cancel' : state.isRecording ? 'Stop' : 'Record'}</span>
          {state.hotkeyDisplayString ? <span className="transcription-widget__hotkey-badge">({state.hotkeyDisplayString})</span> : null}
        </button>
        <button
          type="button"
          className="transcription-widget__primary-button transcription-widget__primary-button--clear"
          disabled={statusMessage || displayText.length === 0}
          onClick={() => clearTranscription()}
        >
          <TranscriptionSymbol name="clear" size={12} />
          <span>Clear</span>
        </button>
      </div>
    </div>
  );
});
