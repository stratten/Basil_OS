import { stopRecording } from '../bridge/assistantSessionBridge';
import type { AssistantSessionState } from '../state/assistantSessionReducer';
import { ProgressMessage } from './ProgressMessage';
import { NativeSymbol } from './NativeSymbol';

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function RecordingState({
  state,
  showProgressElements,
  progressMessage,
}: {
  state: AssistantSessionState;
  showProgressElements: boolean;
  progressMessage: string | null;
}) {
  const hotkey = state.hotkeyDisplayString;
  return (
    <div className="assistant-session-recording">
      <ProgressMessage show={showProgressElements} message={progressMessage} />
      <div className="assistant-session-recording__status-wrap">
        {state.isRecording ? (
          <>
            <div className="assistant-session-recording__status">
              <button type="button" className="assistant-session-recording__stop-btn" onClick={stopRecording} title="Stop recording">
                <NativeSymbol name="stop" size={18} />
              </button>
              <div className="assistant-session-recording__timer">{formatElapsed(state.elapsedSeconds)}</div>
            </div>
            {hotkey && <div className="assistant-session-recording__hint">Press {hotkey} to stop</div>}
          </>
        ) : (
          <div className="assistant-session-recording__placeholder" />
        )}
      </div>
      {state.errorMessage && <div className="assistant-session-recording__error">Error: {state.errorMessage}</div>}
    </div>
  );
}
