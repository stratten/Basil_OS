import { useEffect, useLayoutEffect, useReducer, useState } from 'react';
import { onAssistantSessionEvent, reportReady, requestResize } from '../bridge/assistantSessionBridge';
import { applyAssistantSessionEvent, initialAssistantSessionState, resolveTheme } from '../state/assistantSessionReducer';
import type { AssistantSessionState } from '../state/assistantSessionReducer';
import { deriveWidgetPhase } from '../lib/widgetPhase';
import { assistantSessionProgressMessage } from '../lib/progressMessage';
import { deriveWidgetSize } from '../lib/widgetSizing';
import { Header } from '../components/Header';
import { RecordingState } from '../components/RecordingState';
import { TypedInputState } from '../components/TypedInputState';
import { ProcessingState } from '../components/ProcessingState';
import { ResultState } from '../components/ResultState';
import { ModelPickerMenu } from '../components/ModelPickerMenu';
import { applyAssistantSessionTheme } from './themeCssVars';

function reducer(state: AssistantSessionState, event: Parameters<typeof applyAssistantSessionEvent>[1]): AssistantSessionState {
  return applyAssistantSessionEvent(state, event);
}

const ASSISTANT_SESSION_AUTOMATIC_MAX_HEIGHT = 900;

export function AssistantSessionApp() {
  const [state, dispatch] = useReducer(reducer, initialAssistantSessionState);
  const [isTypedRefinementMode, setIsTypedRefinementMode] = useState(false);

  useEffect(() => {
    const offEvent = onAssistantSessionEvent(dispatch);
    reportReady();
    return () => {
      offEvent();
    };
  }, []);

  const theme = resolveTheme(state);
  const phase = deriveWidgetPhase(state);
  const widgetSize = deriveWidgetSize(state, phase);

  useEffect(() => {
    applyAssistantSessionTheme(theme);
  }, [theme]);

  useEffect(() => {
    if (state.assistantSessionStatus === 'running') setIsTypedRefinementMode(false);
  }, [state.assistantSessionStatus]);

  useLayoutEffect(() => {
    if (!state.hasSnapshot) return;

    if (phase !== 'result' || state.isResultChromeCollapsed) {
      requestResize(widgetSize.width, widgetSize.height);
      return;
    }

    const frame = document.querySelector<HTMLElement>('.basil-webkit-window-frame');
    const output = document.querySelector<HTMLElement>('.assistant-session-result__output, .assistant-session-result__edit-textarea');
    if (!frame || !output) {
      requestResize(widgetSize.width, widgetSize.height);
      return;
    }

    const chromeHeight = Math.max(0, frame.clientHeight - output.clientHeight);
    const measuredHeight = output.scrollHeight + chromeHeight;
    const automaticHeight = Math.min(
      ASSISTANT_SESSION_AUTOMATIC_MAX_HEIGHT,
      Math.max(widgetSize.height, measuredHeight),
    );

    requestResize(
      Math.max(window.innerWidth, widgetSize.width),
      Math.max(window.innerHeight, automaticHeight),
    );
  }, [
    phase,
    state.assistantOutput,
    state.errorMessage,
    state.hasSnapshot,
    state.isEditMode,
    state.isResultChromeCollapsed,
    state.ocrText,
    state.shouldPersistUI,
    state.thinkingContent,
    state.transcriptionText,
    isTypedRefinementMode,
    widgetSize.height,
    widgetSize.width,
  ]);
  const showProgressElements = !(state.assistantSessionStatus === 'completed' || state.assistantSessionStatus === 'failed');
  const progressMessage = assistantSessionProgressMessage(
    state.ocrStatus,
    state.transcriptionStatus,
    state.assistantSessionStatus,
    state.transcriptionProgressMessage,
  );

  return (
    <div className="basil-webkit-window-frame">
      <div className={`assistant-session-shell assistant-session-shell--${phase} basil-webkit-window-surface`}>
        <Header state={state} theme={theme} phase={phase} showProgressElements={showProgressElements} />
        {phase === 'recording' && (
          <RecordingState state={state} showProgressElements={showProgressElements} progressMessage={progressMessage} />
        )}
        {phase === 'typedInput' && (
          <TypedInputState
            state={state}
            showProgressElements={showProgressElements}
            progressMessage={progressMessage}
          />
        )}
        {phase === 'processing' && (
          <ProcessingState state={state} showProgressElements={showProgressElements} progressMessage={progressMessage} />
        )}
        {phase === 'result' && !state.isResultChromeCollapsed && (
          <ResultState state={state} onTypedRefinementModeChange={setIsTypedRefinementMode} />
        )}
        {state.inputMode === 'speak' && (
          <div className="assistant-session-shell__model-picker">
            <ModelPickerMenu state={state} variant="miniChevron" />
          </div>
        )}
      </div>
    </div>
  );
}
