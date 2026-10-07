import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  editorHtmlToDisplayMarkdown,
  plainTextToDisplayMarkdown,
} from '../../../shared/editorMarkdown';
import type {
  AgentTaskOriginNavigationPayload,
  ConversationMessageItem,
  ConversationVoiceCaptureState,
} from '../contracts';
import {
  deleteConversation,
  getConversationMessages,
  getReasoningModels,
  type ReasoningModel,
} from '../services/api';
import {
  cancelConversationVoiceCapture,
  copyRichTextToClipboard,
  copyToClipboard,
  openConversationThreadWindow,
  pickConversationFiles,
  registerConversationComposerFocusHandler,
  setBoardFileDropTarget,
  startConversationVoiceCapture,
  stopConversationVoiceCapture,
} from '../services/bridge';
import {
  activeConversationIds,
  createDraftThreadSession,
  DRAFT_THREAD_KEY,
  getPersistedConversationSelection,
  getPersistedConversationSessionStore,
  mergeHistoryWithInFlightAgentTaskStatus,
  pendingConversationThreadKey,
  setPersistedConversationSelection,
  setPersistedConversationSessionStore,
  withThread,
  type ConversationDraftSubmission,
  type ConversationSessionStore,
} from './conversationSessionState';
import type { HomeChatHandoff } from '../home/HomeForwardContext';
import { useHomeChatHandoff } from './useHomeChatHandoff';
import ConversationArtifactPreviewSidebar from './conversation-artifact-preview/ConversationArtifactPreviewSidebar';
import { useConversationArtifactPreview } from './conversation-artifact-preview/useConversationArtifactPreview';
import { usePresenceTransition } from '@shared/usePresenceTransition';
import ConversationComposer from './ConversationComposer';
import ConversationSidebar from './ConversationSidebar';
import ConversationTranscript from './ConversationTranscript';
import { useConversationList } from './useConversationList';
import { useConversationNativeInputs } from './useConversationNativeInputs';
import { useConversationWebSocket } from './useConversationWebSocket';
import { useStableReadonlySet } from './useStableReadonlySet';
import { useConversationAutoScroll } from './useConversationAutoScroll';
import { useConversationPreferences } from './useConversationPreferences';
import { resolveThreadDelegationOptOut, withHistoryDelegationOptOut } from './conversationDelegationPreference';
import { focusEditableAtEnd } from './focusEditableAtEnd';
import { plainMarkdownText } from '@shared/plainMarkdownText';
import { hasSwiftHandler } from '@shared/swiftBridge';

interface ConversationWorkspaceProps {
  onConversationSubtitleChange?: (subtitle?: string) => void;
  showConversationHeader?: boolean;
  initialConversationId?: string;
  conversationPresentation?: 'global' | 'thread';
  originNavigation?: AgentTaskOriginNavigationPayload;
  /**
   * Ids of conversations currently open in their own detached window. When
   * the selected conversation is in this set, the transcript/composer are
   * replaced with a placeholder (mirroring the Agent Task tab's per-root
   * `DetachedTaskPlaceholder`) while the sidebar remains fully usable for
   * browsing and selecting other conversations.
   */
  detachedConversationIds?: Set<string>;
  homeHandoff?: HomeChatHandoff;
  onHomeHandoffConsumed?: (nonce: string) => void;
}

function createLocalId(prefix: string): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `${prefix}-${uuid}` : `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function basename(path: string): string {
  const parts = path.split('/');
  return parts[parts.length - 1] || path;
}

function fileType(path: string): string {
  const name = basename(path);
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}

function messageFromSubmission(submission: ConversationDraftSubmission): ConversationMessageItem {
  return {
    id: submission.messageId,
    role: 'user',
    content: submission.content,
    timestamp: new Date().toISOString(),
    metadata: {
      display_markdown: submission.displayMarkdown,
      attached_files: submission.filePaths.map((path) => ({
        filename: basename(path),
        path,
        file_type: fileType(path),
        file_size: 0,
      })),
    },
  };
}

export default function ConversationWorkspace({
  onConversationSubtitleChange,
  showConversationHeader = true,
  initialConversationId,
  conversationPresentation = 'global',
  originNavigation,
  detachedConversationIds,
  homeHandoff,
  onHomeHandoffConsumed,
}: ConversationWorkspaceProps) {
  const {
    conversations,
    query,
    loading: listLoading,
    loadingMore,
    loadError: listError,
    loadMoreError,
    hasMore,
    onQueryChange,
    reload: refreshConversations,
    refresh: refreshConversationsSilently,
    removeConversation,
    loadMore: loadMoreConversations,
  } = useConversationList();

  const [store, setStore] = useState<ConversationSessionStore>(getPersistedConversationSessionStore);
  const [selectedConversationId, setSelectedConversationId] = useState<string | undefined>(
    () => getPersistedConversationSelection().selectedConversationId,
  );
  const artifactPreview = useConversationArtifactPreview({ selectedConversationId });
  const artifactSidebarPresence = usePresenceTransition(Boolean(artifactPreview.selection));
  const retainedArtifactSelection = useRef(artifactPreview.selection);
  if (artifactPreview.selection) retainedArtifactSelection.current = artifactPreview.selection;
  const [selectedPendingThreadKey, setSelectedPendingThreadKey] = useState<string | undefined>(
    () => getPersistedConversationSelection().selectedPendingThreadKey,
  );
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [models, setModels] = useState<ReasoningModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>();
  const [copyError, setCopyError] = useState<string>();
  const [attachmentError, setAttachmentError] = useState<string>();
  const [voiceState, setVoiceState] = useState<ConversationVoiceCaptureState>('idle');
  const [voiceError, setVoiceError] = useState<string>();
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string>();
  const [deleteError, setDeleteError] = useState<string>();
  const [deletingId, setDeletingId] = useState<string>();

  const editorRef = useRef<HTMLDivElement>(null);
  const messageViewportRef = useRef<HTMLDivElement>(null);
  const pinnedToBottom = useRef(true);
  const historyRequestVersions = useRef<Record<string, number>>({});
  const voiceCaptureThreadKeyRef = useRef<string>();

  const selectedThreadKey = selectedConversationId ?? selectedPendingThreadKey ?? DRAFT_THREAD_KEY;
  const selectedThreadKeyRef = useRef(selectedThreadKey);
  useEffect(() => {
    selectedThreadKeyRef.current = selectedThreadKey;
  }, [selectedThreadKey]);

  // Keep the module-level singleton in sync so an in-flight draft, its
  // attachments, and which conversation was selected all survive this
  // component unmounting and remounting (e.g. switching Board tabs away from
  // Conversation and back) within the same app run.
  useEffect(() => {
    setPersistedConversationSessionStore(store);
  }, [store]);
  useEffect(() => {
    setPersistedConversationSelection(selectedConversationId, selectedPendingThreadKey);
  }, [selectedConversationId, selectedPendingThreadKey]);

  useEffect(() => {
    if (selectedConversationId) return;
    if (selectedPendingThreadKey) {
      const selectedPendingRequest = Object.values(store.requestsById).find(
        (request) => pendingConversationThreadKey(request.requestId) === selectedPendingThreadKey,
      );
      if (!selectedPendingRequest) return;
      const resolvedThreadKey = store.requestIdToThreadKey[selectedPendingRequest.requestId];
      if (
        selectedPendingRequest.conversationId
        && resolvedThreadKey === selectedPendingRequest.conversationId
      ) {
        setSelectedConversationId(selectedPendingRequest.conversationId);
        setSelectedPendingThreadKey(undefined);
      }
      return;
    }
    const adoptedRequest = Object.values(store.requestsById).find(
      (request) => request.ownedByThisSocket
        && request.conversationId
        && store.requestIdToThreadKey[request.requestId] === request.conversationId,
    );
    if (adoptedRequest?.conversationId) {
      setSelectedConversationId(adoptedRequest.conversationId);
    }
  }, [store, selectedConversationId, selectedPendingThreadKey]);

  const focusEditor = useCallback(() => {
    editorRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!selectedConversationId) window.requestAnimationFrame(focusEditor);
  }, [focusEditor, selectedConversationId]);

  useEffect(() => registerConversationComposerFocusHandler(() => {
    window.requestAnimationFrame(() => focusEditableAtEnd(editorRef.current));
  }), []);

  const { defaultConversationOnly, refresh: refreshConversationPreferences } = useConversationPreferences();

  const loadHistory = useCallback(async (conversationId: string) => {
    const version = (historyRequestVersions.current[conversationId] ?? 0) + 1;
    historyRequestVersions.current[conversationId] = version;
    setStore((current) => withThread(current, conversationId, (thread) => ({
      ...thread,
      messagesLoading: true,
      messagesError: undefined,
    })));
    try {
      const history = await getConversationMessages(conversationId);
      if (historyRequestVersions.current[conversationId] !== version) return;
      setStore((current) => withThread(current, conversationId, (thread) => withHistoryDelegationOptOut({
        ...thread,
        messages: mergeHistoryWithInFlightAgentTaskStatus(
          thread.messages,
          history.messages.filter((message) => message.role !== 'system'),
        ),
        messagesLoading: false,
      }, history.messages)));
      if (conversationId === selectedThreadKeyRef.current) pinnedToBottom.current = true;
    } catch (error) {
      if (historyRequestVersions.current[conversationId] === version) {
        setStore((current) => withThread(current, conversationId, (thread) => ({
          ...thread,
          messagesLoading: false,
          messagesError: error instanceof Error ? error.message : 'Failed to load messages',
        })));
      }
    }
  }, []);

  useEffect(() => {
    getReasoningModels()
      .then((response) => {
        setModels(response.models);
        setSelectedModelId(response.current_model);
      })
      .catch(() => setModels([]));
  }, []);

  const refreshConversationsForEvents = useCallback(async () => {
    await refreshConversationsSilently();
  }, [refreshConversationsSilently]);

  const { connectionState, submit, cancel } = useConversationWebSocket({
    store,
    setStore,
    loadHistory,
    refreshConversations: refreshConversationsForEvents,
  });

  const selectedThread = store.threadsByKey[selectedThreadKey] ?? createDraftThreadSession(selectedThreadKey);
  const selectedDelegationOptOut = resolveThreadDelegationOptOut(selectedThread, defaultConversationOnly);
  const selectedRequest = selectedThread.activeRequestId ? store.requestsById[selectedThread.activeRequestId] : undefined;
  const processing = Boolean(selectedThread.activeRequestId);
  const canceling = Boolean(selectedRequest?.canceling);
  const rawActiveConversationIds = useMemo(() => activeConversationIds(store), [store]);
  const conversationActiveIds = useStableReadonlySet(rawActiveConversationIds);

  useEffect(() => {
    const viewport = messageViewportRef.current;
    if (viewport && pinnedToBottom.current) viewport.scrollTop = viewport.scrollHeight;
  }, [selectedThread.messages, selectedRequest?.streamState]);

  useEffect(() => {
    pinnedToBottom.current = true;
    if (editorRef.current) editorRef.current.innerHTML = selectedThread.draftHtml;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedThreadKey]);

  useEffect(() => {
    const updateFormats = () => {
      const selection = window.getSelection();
      if (!selection || !editorRef.current?.contains(selection.anchorNode)) return;
      setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({
        ...thread,
        activeFormats: {
          bold: document.queryCommandState('bold'),
          italic: document.queryCommandState('italic'),
          underline: document.queryCommandState('underline'),
          insertUnorderedList: document.queryCommandState('insertUnorderedList'),
          insertOrderedList: document.queryCommandState('insertOrderedList'),
        },
      })));
    };
    document.addEventListener('selectionchange', updateFormats);
    return () => document.removeEventListener('selectionchange', updateFormats);
  }, []);

  const mergeAttachmentPaths = useCallback((paths: string[]) => {
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => {
      const merged = [...thread.attachmentPaths];
      for (const path of paths) if (!merged.includes(path)) merged.push(path);
      return { ...thread, attachmentPaths: merged };
    }));
    setAttachmentError(undefined);
  }, []);

  const sendSubmission = useCallback((
    submission: ConversationDraftSubmission,
    options: { clearComposer: boolean },
    targetThreadKey?: string,
  ) => {
    const threadKey = targetThreadKey
      ?? submission.conversationId
      ?? pendingConversationThreadKey(submission.requestId);
    const sent = submit(threadKey, submission);
    if (!sent) {
      setStore((current) => withThread(current, threadKey, (thread) => ({
        ...thread,
        unsentSubmission: submission,
        responseError: 'Conversation is offline. Your draft was not sent.',
      })));
      return false;
    }
    setStore((current) => withThread(current, threadKey, (thread) => ({
      ...thread,
      // "Conversation only" is a per-thread choice that should persist across
      // messages within the same conversation until the user manually
      // changes it, so it is intentionally not reset here after a send.
      delegationOptOut: submission.delegationOptOut,
      delegationOptOutSource: thread.delegationOptOutSource ?? 'resolved',
      messages: [
        ...thread.messages,
        messageFromSubmission(submission),
        {
          id: `pending-${submission.requestId}`,
          role: 'assistant',
          content: '',
          timestamp: new Date().toISOString(),
          model_id: submission.modelId,
          metadata: { loading: true },
        },
      ],
      draftText: options.clearComposer ? '' : thread.draftText,
      draftHtml: options.clearComposer ? '' : thread.draftHtml,
      attachmentPaths: options.clearComposer ? [] : thread.attachmentPaths,
      activeFormats: options.clearComposer ? {} : thread.activeFormats,
    })));
    if (
      options.clearComposer
      && editorRef.current
      && (threadKey === selectedThreadKeyRef.current || selectedThreadKeyRef.current === DRAFT_THREAD_KEY)
    ) {
      editorRef.current.innerHTML = '';
    }
    if (threadKey === selectedThreadKeyRef.current) pinnedToBottom.current = true;
    if (
      submission.conversationId === undefined
      && targetThreadKey === undefined
      && selectedThreadKeyRef.current === DRAFT_THREAD_KEY
    ) {
      setSelectedPendingThreadKey(threadKey);
    }
    return true;
  }, [submit]);

  const sendVoiceTranscription = useCallback((transcription: string) => {
    const threadKey = voiceCaptureThreadKeyRef.current ?? selectedThreadKeyRef.current;
    const thread = store.threadsByKey[threadKey];
    if (thread?.activeRequestId) {
      setStore((current) => withThread(current, threadKey, (existing) => ({
        ...existing,
        draftText: transcription,
        draftHtml: transcription,
      })));
      if (threadKey === selectedThreadKeyRef.current && editorRef.current) {
        editorRef.current.innerText = transcription;
      }
      return;
    }
    const submission: ConversationDraftSubmission = {
      requestId: createLocalId('request'),
      messageId: createLocalId('message'),
      content: transcription,
      displayMarkdown: plainTextToDisplayMarkdown(transcription),
      conversationId: threadKey === DRAFT_THREAD_KEY ? undefined : threadKey,
      modelId: selectedModelId,
      filePaths: [],
      delegationOptOut: resolveThreadDelegationOptOut(thread ?? createDraftThreadSession(threadKey), defaultConversationOnly),
      source: 'voice',
      editorHtml: '',
    };
    sendSubmission(submission, { clearComposer: false }, threadKey);
  }, [defaultConversationOnly, sendSubmission, selectedModelId, store]);

  const adoptHomeConversation = useCallback((conversationId: string) => {
    setSelectedPendingThreadKey(undefined);
    setSelectedConversationId(conversationId);
  }, []);
  const sendHomeFirstMessage = useCallback(
    (submission: ConversationDraftSubmission, conversationId: string) => (
      sendSubmission(submission, { clearComposer: false }, conversationId)
    ),
    [sendSubmission],
  );
  useHomeChatHandoff({
    handoff: homeHandoff,
    onConsumed: onHomeHandoffConsumed,
    connectionOpen: connectionState === 'open',
    adoptConversation: adoptHomeConversation,
    sendFirstMessage: sendHomeFirstMessage,
  });

  const { handlePastedImages } = useConversationNativeInputs({
    focusEditor,
    onVoiceTranscription: sendVoiceTranscription,
    onAttachmentPaths: mergeAttachmentPaths,
    onAttachmentError: setAttachmentError,
    onVoiceStateChange: setVoiceState,
    onVoiceError: setVoiceError,
  });

  const handleStartVoice = useCallback(() => {
    const currentThreadKey = selectedThreadKeyRef.current;
    if (currentThreadKey === DRAFT_THREAD_KEY) {
      const voiceThreadKey = pendingConversationThreadKey(createLocalId('voice'));
      setStore((current) => {
        const draftThread = current.threadsByKey[DRAFT_THREAD_KEY];
        return withThread(current, voiceThreadKey, (thread) => (
          draftThread?.delegationOptOutSource
            ? { ...thread, delegationOptOut: draftThread.delegationOptOut, delegationOptOutSource: draftThread.delegationOptOutSource }
            : thread
        ));
      });
      voiceCaptureThreadKeyRef.current = voiceThreadKey;
    } else {
      voiceCaptureThreadKeyRef.current = currentThreadKey;
    }
    startConversationVoiceCapture();
  }, []);

  const stopResponse = useCallback(() => {
    cancel(selectedThreadKey);
  }, [cancel, selectedThreadKey]);

  const armConversationFileDropTarget = useCallback(() => {
    setBoardFileDropTarget('conversation');
  }, []);
  const clearConversationFileDropTarget = useCallback(() => {
    setBoardFileDropTarget();
  }, []);

  const selectConversation = useCallback((conversationId: string) => {
    setSelectedPendingThreadKey(undefined);
    setSelectedConversationId(conversationId);
    void loadHistory(conversationId);
  }, [loadHistory]);

  const startNewConversation = useCallback(() => {
    setStore((current) => ({
      ...current,
      threadsByKey: { ...current.threadsByKey, [DRAFT_THREAD_KEY]: createDraftThreadSession(DRAFT_THREAD_KEY) },
    }));
    setSelectedPendingThreadKey(undefined);
    setSelectedConversationId(undefined);
    if (editorRef.current) editorRef.current.innerHTML = '';
    window.requestAnimationFrame(focusEditor);
    refreshConversationPreferences();
  }, [focusEditor, refreshConversationPreferences]);

  const setSelectedDraftText = useCallback((value: string) => {
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({ ...thread, draftText: value })));
  }, []);

  // Mirrors the editor's live HTML into the thread session so switching away
  // from this thread (to another conversation, or unmounting entirely) and
  // back restores the actual rich content, not just its plain-text shadow.
  const setSelectedDraftHtml = useCallback((html: string) => {
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({ ...thread, draftHtml: html })));
  }, []);

  const submitDraft = useCallback(() => {
    const editor = editorRef.current;
    const content = editor?.innerText.trim() ?? '';
    if (processing || canceling || (!content && selectedThread.attachmentPaths.length === 0)) return;
    const displayMarkdown = editor ? editorHtmlToDisplayMarkdown(editor) : content;
    const submission: ConversationDraftSubmission = {
      requestId: createLocalId('request'),
      messageId: createLocalId('message'),
      content,
      displayMarkdown,
      conversationId: selectedConversationId,
      modelId: selectedModelId,
      filePaths: [...selectedThread.attachmentPaths],
      delegationOptOut: selectedDelegationOptOut,
      source: 'composer',
      editorHtml: editor?.innerHTML ?? '',
    };
    sendSubmission(submission, { clearComposer: true });
  }, [processing, canceling, selectedThread, selectedConversationId, selectedModelId, selectedDelegationOptOut, sendSubmission]);

  const restoreFailedSubmission = useCallback((submission: ConversationDraftSubmission) => {
    const threadKey = submission.conversationId ?? DRAFT_THREAD_KEY;
    if (editorRef.current && threadKey === selectedThreadKeyRef.current) {
      editorRef.current.innerHTML = submission.editorHtml;
    }
    setStore((current) => withThread(current, threadKey, (thread) => ({
      ...thread,
      draftText: submission.content,
      draftHtml: submission.editorHtml,
      attachmentPaths: submission.filePaths,
      delegationOptOut: submission.delegationOptOut,
      delegationOptOutSource: 'user',
      persistedFailedSubmission: undefined,
      responseError: undefined,
    })));
    if (threadKey === selectedThreadKeyRef.current) focusEditor();
  }, [focusEditor]);

  const executeCommand = useCallback((command: string, value?: string) => {
    focusEditor();
    document.execCommand(command, false, value);
    setSelectedDraftText(editorRef.current?.innerText.trim() ?? '');
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({
      ...thread,
      activeFormats: { ...thread.activeFormats, [command]: document.queryCommandState(command) },
    })));
  }, [focusEditor, setSelectedDraftText]);

  const toggleInlineCode = useCallback(() => {
    focusEditor();
    const selection = window.getSelection();
    const editor = editorRef.current;
    if (!selection || !editor || selection.rangeCount === 0 || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.commonAncestorContainer)) return;
    const commonElement = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
      ? range.commonAncestorContainer as Element
      : range.commonAncestorContainer.parentElement;
    const existingCode = commonElement?.closest('code');
    if (existingCode && editor.contains(existingCode)) {
      existingCode.replaceWith(document.createTextNode(existingCode.textContent ?? ''));
    } else {
      const code = document.createElement('code');
      code.append(range.extractContents());
      range.insertNode(code);
      selection.removeAllRanges();
      const nextRange = document.createRange();
      nextRange.selectNodeContents(code);
      selection.addRange(nextRange);
    }
    setSelectedDraftText(editor.innerText.trim());
  }, [focusEditor, setSelectedDraftText]);

  const setDelegationOptOut = useCallback((value: boolean) => {
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({ ...thread, delegationOptOut: value, delegationOptOutSource: 'user' })));
  }, []);

  const removeAttachment = useCallback((path: string) => {
    setStore((current) => withThread(current, selectedThreadKeyRef.current, (thread) => ({
      ...thread,
      attachmentPaths: thread.attachmentPaths.filter((item) => item !== path),
    })));
  }, []);

  const deleteSelectedConversation = useCallback(async (conversationId: string) => {
    if (conversationActiveIds.has(conversationId)) return;
    setDeletingId(conversationId);
    setDeleteError(undefined);
    try {
      await deleteConversation(conversationId);
      removeConversation(conversationId);
      void refreshConversationsSilently();
      if (selectedConversationId === conversationId) startNewConversation();
      setConfirmingDeleteId(undefined);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : 'Failed to delete conversation');
    } finally {
      setDeletingId(undefined);
    }
  }, [conversationActiveIds, refreshConversationsSilently, removeConversation, selectedConversationId, startNewConversation]);

  useEffect(() => {
    if (
      conversationPresentation === 'thread'
      && initialConversationId
      && selectedConversationId !== initialConversationId
    ) {
      selectConversation(initialConversationId);
    }
  }, [conversationPresentation, initialConversationId, selectedConversationId, selectConversation]);

  useEffect(() => {
    // A "From Conversation" chip elsewhere in the app asked the Board to
    // surface a specific conversation here (instead of opening a redundant
    // standalone thread window), so make it the active selection.
    if (originNavigation?.originType !== 'conversation') return;
    selectConversation(originNavigation.originId);
  }, [originNavigation, selectConversation]);

  const copyMessage = useCallback(async (content: string, format: 'markdown' | 'richText') => {
    try {
      if (hasSwiftHandler('basilBoardBridge')) {
        if (format === 'richText') copyRichTextToClipboard(content);
        else copyToClipboard(content);
      } else {
        await navigator.clipboard.writeText(content);
      }
      setCopyError(undefined);
    } catch {
      setCopyError('Could not copy the response.');
      throw new Error('Could not copy the response.');
    }
  }, []);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === selectedConversationId),
    [conversations, selectedConversationId],
  );
  const modelDisplayNames = useMemo(
    () => new Map(models.map((model) => [model.id, model.display_name || model.name])),
    [models],
  );
  const selectedConversationSubtitle = plainMarkdownText(activeConversation?.title) || undefined;
  const canCompose = true;
  const isSelectedConversationDetachedElsewhere = Boolean(
    selectedConversationId && detachedConversationIds?.has(selectedConversationId),
  );
  const voiceBusy = voiceState === 'starting' || voiceState === 'recording' || voiceState === 'processing';
  const sendDisabled = processing || canceling || voiceBusy || (!selectedThread.draftText.trim() && selectedThread.attachmentPaths.length === 0);
  useConversationAutoScroll(messageViewportRef, pinnedToBottom, canCompose && !isSelectedConversationDetachedElsewhere);

  useEffect(() => {
    onConversationSubtitleChange?.(selectedConversationSubtitle);
  }, [onConversationSubtitleChange, selectedConversationSubtitle]);

  const handlePinnedChange = useCallback((pinned: boolean) => {
    pinnedToBottom.current = pinned;
  }, []);

  const retryLoadHistory = useCallback(() => {
    if (selectedConversationId) void loadHistory(selectedConversationId);
  }, [selectedConversationId, loadHistory]);

  const retryUnsentSubmission = useCallback(() => {
    if (selectedThread.unsentSubmission) {
      sendSubmission(selectedThread.unsentSubmission, {
        clearComposer: selectedThread.unsentSubmission.source === 'composer',
      });
    }
  }, [selectedThread.unsentSubmission, sendSubmission]);

  const restoreFailedSubmissionHandler = useCallback(() => {
    if (selectedThread.persistedFailedSubmission) restoreFailedSubmission(selectedThread.persistedFailedSubmission);
  }, [selectedThread.persistedFailedSubmission, restoreFailedSubmission]);

  const pasteImages = useCallback((files: File[]) => {
    void handlePastedImages(files);
  }, [handlePastedImages]);

  const cancelDelete = useCallback(() => {
    setConfirmingDeleteId(undefined);
  }, []);

  const confirmDelete = useCallback((conversationId: string) => {
    void deleteSelectedConversation(conversationId);
  }, [deleteSelectedConversation]);

  return (
    <section className={`capability-tab chats-tab${artifactSidebarPresence.shouldRender ? ' chats-tab-has-artifact-sidebar' : ''}`}>
      {conversationPresentation !== 'thread' ? <ConversationSidebar
        conversations={conversations}
        selectedId={selectedConversationId}
        query={query}
        activeConversationIds={conversationActiveIds}
        loading={listLoading}
        loadError={listError}
        confirmingDeleteId={confirmingDeleteId}
        deletingId={deletingId}
        deleteError={deleteError}
        isCollapsed={isSidebarCollapsed}
        loadingMore={loadingMore}
        loadMoreError={loadMoreError}
        hasMore={hasMore}
        onQueryChange={onQueryChange}
        onRetryLoad={refreshConversations}
        onRetryLoadMore={loadMoreConversations}
        onLoadMore={loadMoreConversations}
        onStartNew={startNewConversation}
        onCollapsedChange={setIsSidebarCollapsed}
        onSelect={selectConversation}
        onRequestDelete={setConfirmingDeleteId}
        onCancelDelete={cancelDelete}
        onConfirmDelete={confirmDelete}
      /> : null}

      <div className="chats-main">
        {showConversationHeader ? (
          <header className="chats-main-header">
            <div>
              <strong>Conversation</strong>
              <span>{selectedConversationSubtitle || (!selectedConversationId ? 'New Conversation' : 'Select a conversation')}</span>
            </div>
            <span className={`chats-connection-state is-${connectionState}`}>
              {connectionState === 'open' ? 'Connected' : connectionState}
            </span>
          </header>
        ) : null}

        {!canCompose ? (
          <div className="chats-empty-state">
            <span className="chats-empty-icon" aria-hidden="true">B</span>
            <p>Select a conversation or start a new one.</p>
          </div>
        ) : isSelectedConversationDetachedElsewhere ? (
          <div className="chats-empty-state" role="status">
            <span className="chats-empty-icon" aria-hidden="true">B</span>
            <p>This conversation is open in a separate window.</p>
            <p>Close that window to view it here.</p>
            <button
              type="button"
              className="action-btn primary"
              onClick={() => {
                if (selectedConversationId) openConversationThreadWindow(selectedConversationId);
              }}
            >
              Bring window to front
            </button>
          </div>
        ) : (
          <>
            <ConversationTranscript
              viewportRef={messageViewportRef}
              messages={selectedThread.messages}
              loading={selectedThread.messagesLoading}
              loadError={selectedThread.messagesError}
              selectedId={selectedConversationId}
              modelDisplayNames={modelDisplayNames}
              onRetryLoad={retryLoadHistory}
              onPinnedChange={handlePinnedChange}
              onCopy={copyMessage}
              onPreviewArtifact={artifactPreview.onPreviewArtifact}
              onViewAllArtifacts={artifactPreview.onViewAllArtifacts}
            />

            <ConversationComposer
              editorRef={editorRef}
              responseError={selectedThread.responseError}
              copyError={copyError}
              attachmentError={attachmentError}
              voiceError={voiceError}
              attachmentPaths={selectedThread.attachmentPaths}
              processing={processing}
              canceling={canceling}
              voiceState={voiceState}
              activeFormats={selectedThread.activeFormats}
              models={models}
              selectedModelId={selectedModelId}
              delegationOptOut={selectedDelegationOptOut}
              onDelegationOptOutChange={setDelegationOptOut}
              sendDisabled={sendDisabled}
              canRetryUnsent={Boolean(selectedThread.unsentSubmission)}
              canRestoreFailed={Boolean(selectedThread.persistedFailedSubmission)}
              onRetryUnsent={retryUnsentSubmission}
              onRestoreFailed={restoreFailedSubmissionHandler}
              onRemoveAttachment={removeAttachment}
              onExecuteCommand={executeCommand}
              onToggleInlineCode={toggleInlineCode}
              onDraftChange={setSelectedDraftText}
              onHtmlChange={setSelectedDraftHtml}
              onSubmit={submitDraft}
              onAttach={pickConversationFiles}
              onModelChange={setSelectedModelId}
              onStartVoice={handleStartVoice}
              onStopVoice={stopConversationVoiceCapture}
              onCancelVoice={cancelConversationVoiceCapture}
              onCancelResponse={stopResponse}
              onPasteImages={pasteImages}
              onArmFileDropTarget={armConversationFileDropTarget}
              onClearFileDropTarget={clearConversationFileDropTarget}
            />
          </>
        )}
      </div>

      {artifactSidebarPresence.shouldRender && retainedArtifactSelection.current ? (
        <ConversationArtifactPreviewSidebar
          selection={retainedArtifactSelection.current}
          transport={artifactPreview.transport}
          onSelectArtifact={artifactPreview.onSelectArtifact}
          onClose={artifactPreview.onCloseSidebar}
          presencePhase={artifactSidebarPresence.phase}
          onPresenceTransitionEnd={artifactSidebarPresence.completeTransition}
        />
      ) : null}
    </section>
  );
}
