import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import * as api from '../services/api';
import type { ReasoningModel } from '../services/api';
import type { DisplayableAgentTask } from '../types';
import { agentStore } from '../store/agentStore';
import { registerFilesPickedHandler, pickFiles } from '../services/bridge';
import { editorHtmlToDisplayMarkdown } from './request/requestMarkdown';
import FollowUpReferences from './FollowUpReferences';
import RichTextComposer from '../../../shared/RichTextComposer';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';

interface Props {
  agentTaskId: string;
  rootTaskId?: string;
  displaySource?: DisplayableAgentTask;
  onCancel: () => void;
  isProcessing?: boolean;
  alwaysVisible?: boolean;
  exiting?: boolean;
  onStartVoiceFollowUp?: () => void;
}

export default function TextFollowUp({
  agentTaskId,
  rootTaskId,
  displaySource,
  onCancel,
  isProcessing = false,
  exiting = false,
  onStartVoiceFollowUp,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [draftContent, setDraftContent] = useState('');
  const [referencePaths, setReferencePaths] = useState<string[]>([]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [availableModels, setAvailableModels] = useState<ReasoningModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputDisabled = submitting || isProcessing || exiting;

  useEffect(() => {
    containerRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'end' });
    editorRef.current?.focus();
  }, []);

  const rootIdForModelPreference = displaySource?.rootTaskId || rootTaskId || agentTaskId;

  useEffect(() => {
    api.getReasoningModels()
      .then((data) => {
        setAvailableModels(data.models);
        setDefaultModelId(data.current_model);
        const agent = agentStore.getAgent(rootIdForModelPreference);
        const previousTurnModel = agent?.originalModelId ?? displaySource?.originalModelId;
        const availableIds = new Set(data.models.map((model) => model.id));
        const usablePreviousTurnModel = previousTurnModel && availableIds.has(previousTurnModel)
          ? previousTurnModel
          : undefined;
        setSelectedModelId(agent?.selectedModelId || usablePreviousTurnModel || data.current_model);
      })
      .catch((error) => console.error('[TextFollowUp] Failed to load models:', error));
  }, [rootIdForModelPreference]);

  useEffect(() => registerFilesPickedHandler((paths) => {
    setReferencePaths((previous) => [...new Set([...previous, ...paths])]);
  }), []);

  const submit = useCallback(() => {
    const content = editorRef.current?.innerText.trim() ?? '';
    if (!content || inputDisabled) return;
    const displayPromptMarkdown = editorRef.current ? editorHtmlToDisplayMarkdown(editorRef.current) : undefined;
    const followUpId = crypto.randomUUID();
    const rootId = displaySource?.rootTaskId || rootTaskId || agentTaskId;
    const parentAgent = agentStore.getAgent(rootId);
    const previousTaskId = parentAgent
      ? agentStore.getCurrentTurnTaskId(rootId)
      : displaySource?.currentTurnTaskId || displaySource?.agentTaskId || agentTaskId;
    const source = parentAgent || displaySource;
    const snapshot = !parentAgent && source && (source.originalPrompt || source.result || source.errorMessage)
      ? {
        id: crypto.randomUUID(),
        agentTaskText: source.originalPrompt,
        displayPromptMarkdown: source.displayPromptMarkdown,
        originType: source.originType,
        originId: source.originId,
        result: source.result,
        files: source.structuredFiles,
        reference_paths: source.referencePaths,
        timestamp: new Date().toISOString(),
        thinkingSegments: source.thinkingSegments,
        executionSteps: source.progressSteps,
        executionTimeline: source.executionTimeline,
        stepDetails: source.stepDetails,
        errorMessage: source.errorMessage,
      }
      : undefined;

    setSubmitting(true);
    agentStore.beginFollowUpTurn(followUpId, rootId, snapshot, previousTaskId, source?.taskTitle);
    agentStore.updateAgentTaskText(rootId, content);
    agentStore.updateAgentDisplayPromptMarkdown(rootId, displayPromptMarkdown || undefined);
    // Publish these immediately so the result surface shows the submitted
    // follow-up's own References section while work is in progress, rather
    // than waiting for terminal-state hydration from the backend.
    agentStore.setReferencePaths(rootId, referencePaths);
    const modelOverride = selectedModelId && selectedModelId !== defaultModelId ? selectedModelId : undefined;
    agentStore.updateOriginalModelId(rootId, selectedModelId ?? defaultModelId ?? undefined);
    agentStore.setSelectedModelId(rootId, undefined);
    api.processAgentTask({
      agent_task: content,
      display_prompt_markdown: displayPromptMarkdown || undefined,
      agent_task_id: followUpId,
      root_task_id: rootId,
      previous_task_id: previousTaskId,
      reference_paths: referencePaths.length > 0 ? referencePaths : undefined,
      model_id: modelOverride,
    }).catch((error) => {
      console.error('[TextFollowUp] Submit failed:', error);
      agentStore.setError(rootId, 'Failed to submit follow-up');
    });
    if (editorRef.current) editorRef.current.innerHTML = '';
    setDraftContent('');
    setReferencePaths([]);
    setSubmitting(false);
    onCancel();
  }, [agentTaskId, defaultModelId, displaySource, inputDisabled, onCancel, referencePaths, rootTaskId, selectedModelId]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    if (event.key === 'Escape') {
      event.preventDefault();
      onCancel();
    }
  }

  function handleDragOver(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingOver(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setIsDraggingOver(false);
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    event.stopPropagation();
    setIsDraggingOver(false);
  }

  return (
    <div
      ref={containerRef}
      className="text-followup"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDraggingOver ? (
        <div
          className="text-followup-drop-overlay"
          aria-hidden="true"
          style={{
            position: 'absolute', inset: 0, borderRadius: 'var(--corner-radius-medium, 8px)',
            background: 'rgba(0,48,135,0.15)', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', zIndex: 10,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="var(--secondary)" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M8 10V2M5 5l3-3 3 3" />
            <path d="M2 10v3a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-3" />
          </svg>
          <span style={{ fontFamily: 'var(--font-family-medium)', fontSize: 'var(--font-size-status-tiny)', color: 'var(--secondary)', marginTop: 4 }}>Drop files here</span>
        </div>
      ) : null}
      <RichTextComposer
        editorRef={editorRef}
        editorClassName="text-followup-editor"
        disabled={inputDisabled}
        placeholder="Type a follow-up..."
        submitDisabled={inputDisabled || !draftContent.trim()}
        onDraftChange={setDraftContent}
        onSubmit={submit}
        onKeyDown={handleKeyDown}
        toolbarEnd={(
          <button
            type="button"
            className="text-followup-action-btn"
            onClick={() => pickFiles()}
            disabled={inputDisabled}
            title="Attach files or folders"
            aria-label="Attach files or folders"
          >
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
            </svg>
          </button>
        )}
        bottomStart={(
          <ReasoningModelPicker
            models={availableModels}
            selectedModelId={selectedModelId ?? undefined}
            disabled={inputDisabled}
            onModelChange={(modelId) => {
              setSelectedModelId(modelId ?? null);
              agentStore.setSelectedModelId(rootIdForModelPreference, modelId);
            }}
          />
        )}
        bottomEnd={(
          onStartVoiceFollowUp ? (
            <button
              type="button"
              className="text-followup-action-btn"
              onClick={onStartVoiceFollowUp}
              disabled={inputDisabled}
              title="Voice follow-up"
              aria-label="Voice follow-up"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <rect x="5.5" y="1" width="5" height="8" rx="2.5" />
                <path d="M3.5 7a4.5 4.5 0 0 0 9 0" />
                <line x1="8" y1="11.5" x2="8" y2="14" />
                <line x1="5.5" y1="14" x2="10.5" y2="14" />
              </svg>
            </button>
          ) : undefined
        )}
      />
      <FollowUpReferences
        paths={referencePaths}
        onRemove={(index) => setReferencePaths((previous) => previous.filter((_, itemIndex) => itemIndex !== index))}
      />
    </div>
  );
}
