// web-components/TranscriptionWidget/src/components/MinimizedWidget.tsx

import { memo, useEffect, useState } from 'react';
import { closeWidget, toggleMinimizedState, toggleRecording } from '../bridge/transcriptionWidgetBridge';
import { TranscriptionAudioBubble } from './TranscriptionAudioBubble';
import { TimerDisplay } from './TimerDisplay';
import { TranscriptionModelPickerMenu } from './TranscriptionModelPickerMenu';
import { ErrorBadgePopover } from './ErrorBadgePopover';
import { TranscriptionSymbol } from './TranscriptionSymbol';
import type { TranscriptionState } from '../state/transcriptionReducer';
import { resolveTheme } from '../state/transcriptionReducer';

export const MinimizedWidget = memo(function MinimizedWidget({ state }: { state: TranscriptionState }) {
  const [isNativeDragAreaHovered, setIsNativeDragAreaHovered] = useState(false);
  const theme = resolveTheme(state);
  const canCancelBeforeClose = state.isRecording || state.isStartingRecording;
  const showHoverControls = isNativeDragAreaHovered;

  useEffect(() => {
    const handleNativeHover = (event: Event) => {
      setIsNativeDragAreaHovered(Boolean((event as CustomEvent<boolean>).detail));
    };
    window.addEventListener('basilTranscriptionNativeHover', handleNativeHover);
    return () => window.removeEventListener('basilTranscriptionNativeHover', handleNativeHover);
  }, []);

  function handleCloseClick(): void {
    closeWidget();
  }

  return (
    <div className="transcription-widget transcription-widget--minimized">
      <div className="transcription-widget__column transcription-widget__column--left">
        <button
          type="button"
          className="transcription-widget__icon-button"
          style={{ opacity: showHoverControls ? 1 : 0 }}
          title={canCancelBeforeClose ? 'Cancel recording and close' : 'Close widget'}
          onClick={handleCloseClick}
        >
          <TranscriptionSymbol name="close" size={13} />
        </button>
        <div className="transcription-widget__spacer" />
        <button
          type="button"
          className="transcription-widget__icon-button"
          style={{ opacity: showHoverControls ? 1 : 0 }}
          aria-label="Expand widget"
          onClick={() => toggleMinimizedState()}
        >
          <TranscriptionSymbol name="expand" size={15} />
        </button>
      </div>

      <div className="transcription-widget__bubble">
        <TranscriptionAudioBubble size={50} bubbleMode={state.bubbleMode} bubbleColors={state.bubbleColors} />
      </div>

      <div className="transcription-widget__column transcription-widget__column--right">
        <button
          type="button"
          className="transcription-widget__record-button"
          style={{
            color: state.isRecording ? theme.recordingBase : theme.primary,
            opacity: state.isRecording ? (showHoverControls ? 1 : 0.4) : showHoverControls ? 1 : 0,
          }}
          title={state.isStartingRecording ? 'Cancel recording startup' : state.isRecording ? 'Stop recording' : 'Start recording'}
          disabled={!state.canToggleRecording}
          onClick={() => toggleRecording()}
        >
          <TranscriptionSymbol name={state.isStartingRecording ? 'closeFill' : state.isRecording ? 'stop' : 'record'} size={18} />
        </button>
        <div
          className="transcription-widget__timer-wrapper"
          style={{ opacity: state.isRecording ? (showHoverControls ? 1 : 0.4) : showHoverControls ? 0.5 : 0 }}
        >
          <TimerDisplay seconds={state.elapsedSeconds} compact />
        </div>
      </div>

      <div
        className="transcription-widget__mini-picker"
        style={{
          opacity: showHoverControls ? 0.72 : 0,
          pointerEvents: showHoverControls ? 'auto' : 'none',
        }}
      >
        <TranscriptionModelPickerMenu state={state} style="miniChevron" />
      </div>

      <div className="transcription-widget__error-badge">
        <ErrorBadgePopover error={state.error} />
      </div>
    </div>
  );
});
