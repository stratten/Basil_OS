import type { AssistantSessionState } from '../state/assistantSessionReducer';
import { ProgressMessage } from './ProgressMessage';
import { ThinkingDisclosure } from './ThinkingDisclosure';

export function ProcessingState({
  state,
  showProgressElements,
  progressMessage,
}: {
  state: AssistantSessionState;
  showProgressElements: boolean;
  progressMessage: string | null;
}) {
  return (
    <div className="assistant-session-processing">
      <ProgressMessage show={showProgressElements} message={progressMessage} />
      {state.errorMessage && <div className="assistant-session-processing__error">Error: {state.errorMessage}</div>}
      {state.transcriptionText && (
        <div className="assistant-session-processing__request">
          <div className="assistant-session-processing__request-label">Request:</div>
          <div className="assistant-session-processing__request-body">{state.transcriptionText}</div>
        </div>
      )}
      {state.thinkingContent && (
        <ThinkingDisclosure content={state.thinkingContent} startsExpanded isActive />
      )}
    </div>
  );
}
