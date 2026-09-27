import { useEffect, useState } from 'react';
import { applyEdits, enterTypedRefinement } from '../bridge/assistantSessionBridge';
import { ThinkingDisclosure } from './ThinkingDisclosure';
import { ActionButtons } from './result/ActionButtons';
import { ContextSection } from './result/ContextSection';
import { OutputCard } from './result/OutputCard';
import { RefinementPanel } from './result/RefinementPanel';
import { RequestSection } from './result/RequestSection';
import type { AssistantSessionState } from '../state/assistantSessionReducer';

export function ResultState({
  state,
  onTypedRefinementModeChange,
}: {
  state: AssistantSessionState;
  onTypedRefinementModeChange?: (isOpen: boolean) => void;
}) {
  const [editedContent, setEditedContent] = useState(state.editableContentSeed);
  const [lastAppliedContent, setLastAppliedContent] = useState<string | null>(null);
  const [isTypedRefinementMode, setIsTypedRefinementMode] = useState(false);

  useEffect(() => {
    if (state.isEditMode) {
      setEditedContent(state.editableContentSeed);
    }
  }, [state.isEditMode, state.editableContentSeed]);

  useEffect(() => {
    if (state.assistantSessionStatus === 'running') {
      setIsTypedRefinementMode(false);
      onTypedRefinementModeChange?.(false);
      setLastAppliedContent(null);
    }
  }, [onTypedRefinementModeChange, state.assistantSessionStatus]);

  return (
    <div className="assistant-session-result">
      {state.assistantSessionStatus === 'failed' && (
        <div className="assistant-session-result__error">{state.errorMessage ?? 'Something went wrong.'}</div>
      )}
      {state.transcriptionText && <RequestSection text={state.transcriptionText} />}
      {state.ocrText && <ContextSection text={state.ocrText} />}
      {state.thinkingContent && <ThinkingDisclosure content={state.thinkingContent} />}
      <OutputCard
        output={state.assistantOutput}
        isEditMode={state.isEditMode}
        editedContent={editedContent}
        onEditedContentChange={setEditedContent}
        fallbackModelUsed={state.fallbackModelUsed}
      />
      <ActionButtons
        state={state}
        sampleContent={state.isEditMode ? editedContent : lastAppliedContent ?? state.assistantOutput}
        isTypedRefinementMode={isTypedRefinementMode}
        onApplyEdits={() => {
          setLastAppliedContent(editedContent);
          applyEdits(editedContent);
        }}
        onEnterTypedRefinement={() => {
          enterTypedRefinement();
          setIsTypedRefinementMode(true);
          onTypedRefinementModeChange?.(true);
        }}
      />
      <RefinementPanel
        state={state}
        isTypedRefinementMode={isTypedRefinementMode}
        onCloseTypedRefinement={() => {
          setIsTypedRefinementMode(false);
          onTypedRefinementModeChange?.(false);
        }}
      />
    </div>
  );
}
