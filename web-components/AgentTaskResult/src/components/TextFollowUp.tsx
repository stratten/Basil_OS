import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react';
import * as api from '../services/api';
import type { ReasoningModel } from '../services/api';
import type { DisplayableAgentTask } from '../types';
import { agentStore } from '../store/agentStore';
import { registerFilesPickedHandler, pickFiles } from '../services/bridge';
import { editorHtmlToDisplayMarkdown } from './request/requestMarkdown';
import { buildFollowUpHistoryFromViewedDetail } from '../app/followUpHistory';
import { seedDurableFollowUpHistory } from '../app/agentHydration';
import FollowUpReferences from './FollowUpReferences';
import { scrollVerticallyIntoView } from './scrollVerticallyIntoView';
import RichTextComposer from '../../../shared/RichTextComposer';
import ReasoningModelPicker from '../../../shared/ReasoningModelPicker';
import AttachmentDropZone from '../../../shared/AttachmentDropZone';
import CollapsibleRegion from '../../../shared/CollapsibleRegion';
import ExecutionDisclosureChevron from '../../../shared/ExecutionDisclosureChevron';
import { useFollowUpComposerCollapsed } from '../store/followUpComposerViewStore';
import { consumeFollowUpPrefill, reportFollowUpDraft, useFollowUpPrefillRequest } from '../store/followUpPrefillStore';
import { addDraftLine, removeDraftLine } from './followUpDraftLines';
import {
  forgetComposerDraft,
  loadComposerDraft,
  moveComposerDraft,
  rememberComposerHtml,
  rememberComposerReferences,
  subscribeComposerDraftDiscarded,
} from '../store/composerDraftStore';

const COLLAPSED_DRAFT_PREVIEW_CHARS = 80;

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
  alwaysVisible = false,
  exiting = false,
  onStartVoiceFollowUp,
}: Props) {
  const [submitting, setSubmitting] = useState(false);
  const [draftContent, setDraftContent] = useState('');
  const rootIdForModelPreference = displaySource?.rootTaskId || rootTaskId || agentTaskId;
  // What was typed here and not sent comes back with the box: it unmounts whenever its task is switched away from, and a fresh one starts empty.
  const [referencePaths, setReferencePaths] = useState<string[]>(
    () => loadComposerDraft('follow-up', rootIdForModelPreference)?.referencePaths ?? [],
  );
  const [availableModels, setAvailableModels] = useState<ReasoningModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [defaultModelId, setDefaultModelId] = useState<string | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputDisabled = submitting || isProcessing || exiting;

  const [collapsed, setCollapsed] = useFollowUpComposerCollapsed(rootIdForModelPreference);
  const bodyId = useId();
  const wasCollapsedRef = useRef(collapsed);
  const barRef = useRef<HTMLButtonElement>(null);

  // The box is always offered once a task finishes, so mounting is not a request to type. Only an explicit follow-up (hotkey or the follow-up action) opens a folded box and takes focus; a folded box that merely reappears stays folded.
  useEffect(() => {
    if (alwaysVisible && collapsed) return;
    if (collapsed) setCollapsed(false);
    if (containerRef.current) scrollVerticallyIntoView(containerRef.current, { block: 'end', behavior: 'smooth' });
    editorRef.current?.focus();
    // Mount only: later collapse changes are the reader's own and are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (wasCollapsedRef.current && !collapsed) editorRef.current?.focus();
    // The collapse control lives inside the region that just became inert, so focus moves to the bar that replaces it rather than falling back to the page.
    if (!wasCollapsedRef.current && collapsed) barRef.current?.focus();
    wasCollapsedRef.current = collapsed;
  }, [collapsed]);

  // Put the saved text back before the first paint, and before the chip effect below so a pending chip request lands on top of it rather than being overwritten.
  useLayoutEffect(() => {
    const editor = editorRef.current;
    const saved = loadComposerDraft('follow-up', rootIdForModelPreference);
    if (!editor || !saved?.html) return;
    editor.innerHTML = saved.html;
    setDraftContent((editor.innerText ?? editor.textContent ?? '').trim());
    // Mount only: later key changes are handled by the move below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The same chain can start to be identified differently while the box stays open, for example once its root is known. The draft goes with it instead of staying behind under the old key.
  const draftKeyRef = useRef(rootIdForModelPreference);
  useEffect(() => {
    if (draftKeyRef.current === rootIdForModelPreference) return;
    moveComposerDraft('follow-up', draftKeyRef.current, rootIdForModelPreference);
    draftKeyRef.current = rootIdForModelPreference;
  }, [rootIdForModelPreference]);

  // A follow-up sent some other way, such as by voice, answers whatever was typed here. The stored draft is dropped by the store; a box that stays mounted through that must empty itself too, or it would show the old text and save it again on the next keystroke.
  useEffect(() => subscribeComposerDraftDiscarded((kind, taskKey) => {
    if (kind !== 'follow-up' || taskKey !== rootIdForModelPreference) return;
    if (editorRef.current) editorRef.current.innerHTML = '';
    setDraftContent('');
    setReferencePaths([]);
  }), [rootIdForModelPreference]);

  useEffect(() => {
    rememberComposerReferences('follow-up', rootIdForModelPreference, referencePaths);
  }, [referencePaths, rootIdForModelPreference]);

  const rememberDraftHtml = useCallback((html: string) => {
    const editor = editorRef.current;
    const hasText = (editor?.innerText ?? editor?.textContent ?? '').trim() !== '';
    rememberComposerHtml('follow-up', rootIdForModelPreference, html, hasText);
  }, [rootIdForModelPreference]);

  // A suggested follow-up chip asks for its text to be placed in the box as an editable draft. It opens a folded box, takes focus, and never sends.
  const prefillRequest = useFollowUpPrefillRequest(rootIdForModelPreference);
  useEffect(() => {
    if (!prefillRequest || inputDisabled) return;
    const editor = editorRef.current;
    if (!editor) return;
    setCollapsed(false);
    if (prefillRequest.mode === 'replace') {
      editor.textContent = prefillRequest.text;
      setDraftContent(prefillRequest.text);
    } else {
      if (prefillRequest.mode === 'add') addDraftLine(editor, prefillRequest.text);
      else removeDraftLine(editor, prefillRequest.text);
      setDraftContent(editor.innerText.trim());
    }
    editor.dispatchEvent(new Event('input', { bubbles: true }));
    editor.focus();
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    consumeFollowUpPrefill(rootIdForModelPreference, prefillRequest.nonce);
  }, [prefillRequest, inputDisabled, rootIdForModelPreference, setCollapsed]);

  // Suggested chips show which of their lines are in the box, so they read the draft from here. A box that goes away reports an empty draft.
  useEffect(() => {
    reportFollowUpDraft(rootIdForModelPreference, draftContent);
  }, [draftContent, rootIdForModelPreference]);
  useEffect(() => () => reportFollowUpDraft(rootIdForModelPreference, ''), [rootIdForModelPreference]);

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
    // Reopened from history there is no store entry yet, so the whole chain on screen must be carried over. Snapshotting only the current turn collapsed an N-turn thread to "Initial request / Follow-up 1".
    const carriedHistory = !parentAgent && displaySource
      ? buildFollowUpHistoryFromViewedDetail(displaySource)
      : [];
    const snapshot = carriedHistory.length > 0 ? carriedHistory[carriedHistory.length - 1] : undefined;

    setSubmitting(true);
    agentStore.beginFollowUpTurn(followUpId, rootId, snapshot, previousTaskId, source?.taskTitle);
    if (carriedHistory.length > 0) {
      agentStore.setAgentTaskHistory(rootId, carriedHistory);
    } else if (parentAgent) {
      // A chain opened live holds only its newest turn, so the earlier ones are filled in from the backend.
      void seedDurableFollowUpHistory(rootId, followUpId);
    }
    agentStore.updateAgentTaskText(rootId, content);
    agentStore.updateAgentDisplayPromptMarkdown(rootId, displayPromptMarkdown || undefined);
    // Publish these immediately so the result surface shows the submitted
    // follow-up's own References section while work is in progress, rather
    // than waiting for terminal-state hydration from the backend.
    agentStore.setReferencePaths(rootId, referencePaths);
    // A follow-up is not given the earlier run's connection instructions.
    agentStore.setConnectionReferences(rootId, []);
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
    forgetComposerDraft('follow-up', rootId);
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

  const draftPreview = draftContent.trim().replace(/\s+/g, ' ');
  const draftPreviewText = draftPreview.length > COLLAPSED_DRAFT_PREVIEW_CHARS
    ? `${draftPreview.slice(0, COLLAPSED_DRAFT_PREVIEW_CHARS)}...`
    : draftPreview;

  return (
    <div className="text-followup-collapsible">
      {/* The bar exists only while folded. Open, the box is just the text area and the collapse arrow rides in its toolbar, so no separate row spends vertical space. */}
      {collapsed && (
        <button
          ref={barRef}
          type="button"
          className="text-followup-bar"
          aria-expanded={false}
          aria-controls={bodyId}
          aria-label="Open the follow-up box"
          onClick={() => setCollapsed(false)}
        >
          <ExecutionDisclosureChevron expanded={false} color="var(--text-primary)" />
          <span className="text-followup-bar-title">Follow up</span>
          {draftPreviewText !== '' && <span className="text-followup-bar-draft">Draft: {draftPreviewText}</span>}
        </button>
      )}
      <CollapsibleRegion expanded={!collapsed} id={bodyId}>
        <div className="text-followup-collapsible-body">
          <AttachmentDropZone zoneRef={containerRef} className="text-followup">
            <RichTextComposer
              editorRef={editorRef}
              editorClassName="text-followup-editor"
              disabled={inputDisabled}
              placeholder="Type a follow-up..."
              submitDisabled={inputDisabled || !draftContent.trim()}
              onDraftChange={setDraftContent}
              onHtmlChange={rememberDraftHtml}
              onSubmit={submit}
              onKeyDown={handleKeyDown}
              toolbarEnd={(
                <>
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
                  <button
                    type="button"
                    className="text-followup-action-btn text-followup-collapse-btn"
                    aria-expanded
                    aria-controls={bodyId}
                    onClick={() => setCollapsed(true)}
                    title="Collapse the follow-up box"
                    aria-label="Collapse the follow-up box"
                  >
                    <ExecutionDisclosureChevron expanded color="currentColor" />
                  </button>
                </>
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
          </AttachmentDropZone>
        </div>
      </CollapsibleRegion>
    </div>
  );
}
