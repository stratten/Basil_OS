import { useEffect, useRef, useState } from 'react';
import type {
  AgentTaskOriginNavigationPayload,
  TodoItemSummary,
  TodoWorkspaceErrorEvent,
  TodoWorkspaceResultEvent,
  WSEvent,
} from '../contracts';
import { basilBoardWebSocket } from '../services/websocket';
import RichTextComposer from '../../../shared/RichTextComposer';
import ConversationModelPicker from '../capabilities/ConversationModelPicker';
import { getReasoningModels, type ReasoningModel } from '../services/api';
import {
  pickTodoWorkspaceFiles,
  registerTodoWorkspaceFilesPickedHandler,
  setBoardFileDropTarget,
} from '../services/bridge';
import NativeSymbolIcon from '../components/NativeSymbolIcon';
import {
  appendUserMessage,
  applyWorkspaceError,
  applyWorkspaceResult,
  clearWorkspace,
  createWorkspaceState,
  type WorkspaceState,
} from './todoState';
import { useTodoWorkspacePaneResize } from './useTodoWorkspacePaneResize';

interface TodoWorkspacePaneProps {
  selectedItems: TodoItemSummary[];
  onWorkerOrManagerResultSettled: () => void;
  onBusyChange?: (busy: boolean) => void;
  focusRequest?: AgentTaskOriginNavigationPayload;
  onDeselectItem: (id: string) => void;
}

function newWorkspaceId(): string {
  return `todo-workspace-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

export default function TodoWorkspacePane({
  selectedItems, onWorkerOrManagerResultSettled, onBusyChange, focusRequest, onDeselectItem,
}: TodoWorkspacePaneProps) {
  const [state, setState] = useState<WorkspaceState>(() => createWorkspaceState(newWorkspaceId()));
  const [draft, setDraft] = useState('');
  const [referencePaths, setReferencePaths] = useState<string[]>([]);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [models, setModels] = useState<ReasoningModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>();
  const [isExpanded, setIsExpanded] = useState(true);
  const isBusy = state.pendingRequestId !== null;
  const editorRef = useRef<HTMLDivElement>(null);
  const paneResize = useTodoWorkspacePaneResize();

  useEffect(() => {
    if (focusRequest?.originType !== 'todo_workspace') return;
    setIsExpanded(true);
    requestAnimationFrame(() => {
      editorRef.current?.scrollIntoView({ block: 'center' });
      editorRef.current?.focus();
    });
  }, [focusRequest]);
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    onBusyChange?.(isBusy);
  }, [isBusy, onBusyChange]);

  useEffect(() => {
    let mounted = true;
    getReasoningModels()
      .then((result) => {
        if (!mounted) return;
        setModels(result.models);
        setSelectedModelId(result.current_model ?? undefined);
      })
      .catch((error) => console.error('[TodoWorkspacePane] Failed to load models:', error));
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => registerTodoWorkspaceFilesPickedHandler((paths) => {
    setReferencePaths((previous) => [...new Set([...previous, ...paths])]);
  }), []);

  useEffect(() => () => {
    setBoardFileDropTarget();
  }, []);

  useEffect(() => {
    const unsubscribe = basilBoardWebSocket.subscribe((event: WSEvent) => {
      if (event.event_type === 'todo_workspace_result') {
        const resultEvent = event as unknown as TodoWorkspaceResultEvent;
        const current = stateRef.current;
        if (
          resultEvent.workspace_id !== current.workspaceId
          || resultEvent.request_id !== current.pendingRequestId
        ) {
          return;
        }
        setState((current) => applyWorkspaceResult(current, resultEvent));
        onWorkerOrManagerResultSettled();
      } else if (event.event_type === 'todo_workspace_error') {
        const errorEvent = event as unknown as TodoWorkspaceErrorEvent;
        const current = stateRef.current;
        if (
          errorEvent.workspace_id !== current.workspaceId
          || errorEvent.request_id !== current.pendingRequestId
        ) {
          return;
        }
        setState((current) => applyWorkspaceError(current, errorEvent.workspace_id, errorEvent.request_id, errorEvent.message));
      }
    });
    return unsubscribe;
  }, [onWorkerOrManagerResultSettled]);

  function handleDragOver(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setBoardFileDropTarget('todoWorkspace');
    setIsDraggingOver(true);
  }

  function handleDragLeave(event: React.DragEvent<HTMLDivElement>): void {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && event.currentTarget.contains(nextTarget)) return;
    setBoardFileDropTarget();
    setIsDraggingOver(false);
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setBoardFileDropTarget();
    setIsDraggingOver(false);
  }

  function startNewConversation(): void {
    setState(clearWorkspace(newWorkspaceId()));
    if (editorRef.current) editorRef.current.innerHTML = '';
    setDraft('');
    setReferencePaths([]);
  }

  function send(): void {
    if (!draft.trim() || isBusy) return;
    const requestId = `${state.workspaceId}-${Date.now()}`;
    const nextState = appendUserMessage(state, requestId, draft);
    onBusyChange?.(true);
    setState(nextState);
    const sent = basilBoardWebSocket.sendTodoWorkspaceMessage({
      workspaceId: state.workspaceId,
      requestId,
      message: draft,
      selectedTodoIds: selectedItems.map((item) => item.id),
      referencePaths,
      transcript: nextState.transcript
        .filter((entry) => entry.role !== 'error')
        .map((entry) => ({ role: entry.role as 'user' | 'assistant', content: entry.content })),
      modelId: selectedModelId,
    });
    if (!sent) {
      setState((current) => applyWorkspaceError(current, current.workspaceId, requestId, 'Not connected to Basil.'));
      return;
    }
    if (editorRef.current) editorRef.current.innerHTML = '';
    setDraft('');
    setReferencePaths([]);
  }

  return (
    <div
      className={`todo-workspace-pane${isExpanded ? '' : ' todo-workspace-pane--collapsed'}${paneResize.isResizing ? ' todo-workspace-pane--resizing' : ''}`}
      style={paneResize.paneStyle}
    >
      {isExpanded && (
        <div
          className="todo-workspace-pane-resize-handle"
          role="separator"
          tabIndex={0}
          aria-label="Resize To-Do workspace"
          aria-orientation="vertical"
          aria-valuemin={300}
          aria-valuemax={paneResize.maximumWidth}
          aria-valuenow={paneResize.width}
          {...paneResize.resizeHandleProps}
        />
      )}
      <header className="todo-workspace-header">
        <div className="todo-workspace-heading">
          <h3>To-Do workspace</h3>
          <button
            type="button"
            className="todo-workspace-collapse"
            onClick={() => setIsExpanded((current) => !current)}
            disabled={isBusy}
            aria-expanded={isExpanded}
            aria-label={isExpanded ? 'Collapse To-Do workspace' : 'Expand To-Do workspace'}
            title={isExpanded ? 'Collapse workspace' : 'Expand workspace'}
          >
            <NativeSymbolIcon name={isExpanded ? 'conversationSidebar' : 'conversationSidebarExpand'} size={14} />
          </button>
        </div>
        <span className="todo-workspace-selection-count">{selectedItems.length} selected</span>
        <div hidden={!isExpanded}>
          {selectedItems.length === 0 ? (
            <p>No To-Dos selected — attach files or describe work to create candidate To-Dos.</p>
          ) : (
            <ul className="todo-workspace-selection-chips" aria-label="Selected To-Dos">
              {selectedItems.map((item) => (
                <li key={item.id} className="todo-workspace-selection-chip" title={item.title}>
                  <span className="todo-workspace-selection-chip-title">{item.title}</span>
                  <span className="todo-workspace-selection-chip-status">{item.status.replace(/_/g, ' ')}</span>
                  {item.attention.needs_attention && (
                    <span className="todo-workspace-selection-chip-attention" title={item.attention.reason ?? 'Needs attention'}>!</span>
                  )}
                  <button
                    type="button"
                    onClick={() => onDeselectItem(item.id)}
                    disabled={isBusy}
                    aria-label={`Remove ${item.title} from the workspace`}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="todo-workspace-header-actions">
            <button type="button" disabled={isBusy} onClick={startNewConversation}>New conversation</button>
            <button type="button" disabled={isBusy} onClick={() => setState((current) => ({ ...current, transcript: [] }))}>Clear</button>
          </div>
        </div>
      </header>
      <div hidden={!isExpanded} aria-hidden={!isExpanded}>
          <div className="todo-workspace-transcript">
            {state.transcript.length === 0 && <p className="todo-workspace-empty">No messages yet this session.</p>}
            {state.transcript.map((message) => (
              <div key={message.id} className={`todo-workspace-message todo-workspace-message--${message.role}`}>
                {message.content}
              </div>
            ))}
            {isBusy && (
              <div className="todo-workspace-message todo-workspace-message--working">
                Working
                <span className="todo-workspace-pulsing-dots" aria-hidden="true"><i /><i /><i /></span>
              </div>
            )}
          </div>
          <div
            className={`todo-workspace-composer-region${isDraggingOver ? ' is-drag-over' : ''}`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {isDraggingOver ? <div className="todo-workspace-composer-drop-overlay" aria-hidden="true">Drop files here</div> : null}
            {referencePaths.length > 0 ? (
              <div className="todo-workspace-pending-attachments" aria-label="Pending attachments">
                {referencePaths.map((path) => (
                  <span key={path} title={path}>
                    <strong>{basename(path)}</strong>
                    <button
                      type="button"
                      onClick={() => setReferencePaths((previous) => previous.filter((item) => item !== path))}
                      disabled={isBusy}
                      aria-label={`Remove ${basename(path)}`}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : null}
            <RichTextComposer
              editorRef={editorRef}
              className="todo-workspace-composer"
              disabled={isBusy}
              placeholder="Ask about, note, or delegate work on selected To-Dos, or create new ones"
              submitDisabled={isBusy || !draft.trim()}
              onDraftChange={setDraft}
              onSubmit={send}
              toolbarEnd={(
                <button
                  type="button"
                  className="text-followup-action-btn"
                  onClick={pickTodoWorkspaceFiles}
                  disabled={isBusy}
                  title="Attach files or folders"
                  aria-label="Attach files or folders"
                >
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M14.5 7.5l-6.3 6.3a3.5 3.5 0 0 1-5-5l6.3-6.3a2.3 2.3 0 0 1 3.3 3.3L6.5 12a1.2 1.2 0 0 1-1.7-1.7l5.8-5.8" />
                  </svg>
                </button>
              )}
              bottomStart={(
                <ConversationModelPicker
                  models={models}
                  selectedModelId={selectedModelId}
                  disabled={isBusy}
                  onModelChange={setSelectedModelId}
                />
              )}
            />
          </div>
      </div>
    </div>
  );
}
