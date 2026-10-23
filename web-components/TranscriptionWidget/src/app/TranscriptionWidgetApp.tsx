// web-components/TranscriptionWidget/src/app/TranscriptionWidgetApp.tsx

import { useEffect, useReducer } from 'react';
import { onTranscriptionEvent, reportReady } from '../bridge/transcriptionWidgetBridge';
import { applyTranscriptionEvent, initialTranscriptionState, resolveTheme } from '../state/transcriptionReducer';
import { applyTranscriptionTheme } from './themeCssVars';
import { MinimizedWidget } from '../components/MinimizedWidget';
import { FullWidget } from '../components/FullWidget';

export function TranscriptionWidgetApp() {
  const [state, dispatch] = useReducer(applyTranscriptionEvent, initialTranscriptionState);

  useEffect(() => {
    const unsubscribeEvents = onTranscriptionEvent(dispatch);
    reportReady();
    return unsubscribeEvents;
  }, []);

  const theme = resolveTheme(state);
  useEffect(() => {
    applyTranscriptionTheme(theme);
  }, [theme]);
  return (
    state.isMinimized ? (
      <div className="transcription-widget-root transcription-widget-root--minimized">
        <div className="basil-webkit-window-frame transcription-widget-window-frame transcription-widget-window-frame--minimized">
          <div className="basil-webkit-window-surface">
            <MinimizedWidget state={state} />
          </div>
        </div>
      </div>
    ) : (
      <div className="basil-webkit-window-frame transcription-widget-window-frame">
        <div className="basil-webkit-window-surface">
          <div className="transcription-widget-root">
            <FullWidget state={state} />
          </div>
        </div>
      </div>
    )
  );
}
