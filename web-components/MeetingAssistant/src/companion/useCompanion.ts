import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import {
  CompanionApiError,
  actOnCompanionItem,
  attachCompanionRoot,
  cancelCompanionInvestigation,
  cancelCompanionWatch,
  companionSocketUrl,
  createCompanionWatch,
  decideCompanionProposal,
  detachCompanionRoot,
  disableCompanion,
  enableCompanion,
  fetchSnapshot,
  patchCompanionSettings,
  sendCompanionChat,
  sendCompanionFeedback,
  startCompanionAudit,
  startCompanionInvestigation,
} from './companionApi';
import { unresolvedInvestigations } from './companionProposals';
import { companionStoreReducer, initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import type {
  CompanionFeedbackAction,
  CompanionItemAction,
  CompanionItemActionResult,
  CompanionMode,
  CompanionProposalDecision,
  CompanionProposalResult,
  CompanionSocketEvent,
  CompanionStatus,
  TimelineEvent,
} from './types';

export interface UseCompanionArgs {
  /** The meeting the pane shows (`ui.displayedMeetingWorkOwnerId`). */
  meetingId: string | null;
  /** Loopback backend port from `ui.companionApiPort`; 0 or less means unavailable. */
  port: number;
  /** The analysis picker selection (`ui.selectedAnalysisModelId`); null means the default reasoning model. */
  selectedModelId: string | null;
  /** True when `meetingId` is the meeting being recorded; sources queued in advance attach to it as soon as its Companion is on. */
  isRecording?: boolean;
}

export interface CompanionController {
  state: CompanionStoreState;
  isLive: boolean;
  isEnabled: boolean;
  pendingRoots: string[];
  actionError: string | null;
  clearActionError: () => void;
  /** Refetches the snapshot; used by the pane's Retry button after a failed load. */
  refresh: () => Promise<void>;
  enable: () => Promise<boolean>;
  disable: () => Promise<boolean>;
  setMode: (mode: CompanionMode) => Promise<boolean>;
  /** Saves what the user wants the Companion to concentrate on for this meeting; an empty string clears it. */
  setFocus: (focus: string) => Promise<boolean>;
  addRoots: (paths: string[]) => Promise<void>;
  removeRoot: (rootId: string) => Promise<boolean>;
  removePendingRoot: (path: string) => void;
  sendFeedback: (itemId: string, action: CompanionFeedbackAction) => Promise<boolean>;
  /** Resolves true when the backend accepted the message, so the composer knows whether to clear its text. */
  sendChat: (text: string) => Promise<boolean>;
  createWatch: (topic: string, instruction: string) => Promise<boolean>;
  cancelWatch: (watchId: string) => Promise<boolean>;
  /** Approves or dismisses a proposal card. Resolves with the backend's answer (a failed start is a normal answer with `state: 'failed'`), or null when the request itself failed, after which the Companion reloads so a stale card corrects itself. */
  decideProposal: (itemId: string, decision: CompanionProposalDecision) => Promise<CompanionProposalResult | null>;
  /** Audits the meeting in the background; false when it could not start, with the reason in `actionError`. */
  runAudit: () => Promise<boolean>;
  /** Make a to-do or hand an agent a note; the click is the approval. Null when it was refused or failed, with the reason in `actionError`. */
  actOnItem: (itemId: string, action: CompanionItemAction) => Promise<CompanionItemActionResult | null>;
  /** Asks the Companion to research a question; the answer arrives as a researched item. */
  investigate: (question: string, replyToMessageId?: string) => Promise<boolean>;
  /** Asks every investigation that has started and produced no item yet to stop. */
  stopInvestigations: () => Promise<boolean>;
  /** The per-meeting switch; turning it off also stops running investigations. */
  setInvestigate: (enabled: boolean) => Promise<boolean>;
}

function describeError(error: unknown): string {
  if (error instanceof CompanionApiError) return error.message;
  return error instanceof Error ? error.message : 'Something went wrong.';
}

/** How long to keep asking for the live meeting's Companion while the backend answers 404 because it has not created the meeting yet (about 18 seconds in all). */
export const NOT_YET_CREATED_RETRY_DELAYS_MS: readonly number[] = [300, 600, 1200, 2400, 4000, 4000, 5000];

function matchesMeeting(frame: CompanionSocketEvent, meetingId: string): boolean {
  return Array.isArray(frame.meeting_ids) && frame.meeting_ids.includes(meetingId);
}

export function useCompanion({ meetingId, port, selectedModelId, isRecording = false }: UseCompanionArgs): CompanionController {
  const [state, dispatch] = useReducer(companionStoreReducer, initialCompanionStoreState);
  const [pendingRoots, setPendingRoots] = useState<string[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const hydrateRef = useRef<() => Promise<void>>(async () => undefined);
  const hydrationGeneration = useRef(0);
  const active = meetingId !== null && port > 0;
  const isRecordingRef = useRef(isRecording);
  isRecordingRef.current = isRecording;

  useEffect(() => {
    hydrationGeneration.current += 1;
    const generation = hydrationGeneration.current;
    if (meetingId === null || port <= 0) {
      dispatch({ type: 'reset', phase: 'idle' });
      hydrateRef.current = async () => undefined;
      return undefined;
    }
    dispatch({ type: 'reset', phase: 'loading' });
    setActionError(null);
    let inFlight = false;
    let wakeRetry: (() => void) | null = null;
    const isCurrent = () => hydrationGeneration.current === generation;

    // Waits out one retry delay, or returns early when a Companion frame for this meeting arrives or the pane moves on.
    const waitBeforeRetry = (delayMs: number) =>
      new Promise<void>((resolve) => {
        const finish = () => {
          clearTimeout(timer);
          wakeRetry = null;
          resolve();
        };
        const timer = setTimeout(finish, delayMs);
        wakeRetry = finish;
      });

    const hydrate = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        // The pane learns the live meeting's id the moment recording starts, which can be before the backend has created the meeting or its Companion session, so a 404 for the meeting being recorded means "not yet", not "missing".
        for (let attempt = 0; ; attempt += 1) {
          try {
            const snapshot = await fetchSnapshot(port, meetingId);
            if (isCurrent()) dispatch({ type: 'hydrated', snapshot });
            return;
          } catch (error) {
            const notYetCreated = error instanceof CompanionApiError && error.status === 404 && isRecordingRef.current;
            if (!notYetCreated || attempt >= NOT_YET_CREATED_RETRY_DELAYS_MS.length || !isCurrent()) {
              if (isCurrent()) dispatch({ type: 'loadFailed', message: describeError(error) });
              return;
            }
            await waitBeforeRetry(NOT_YET_CREATED_RETRY_DELAYS_MS[attempt]);
            if (!isCurrent()) return;
          }
        }
      } finally {
        inFlight = false;
      }
    };
    hydrateRef.current = hydrate;

    const socket = new ReconnectingWebSocket<CompanionSocketEvent>({ logLabel: '[Companion WS]' });
    socket.subscribe((frame) => {
      if (!isCurrent() || !frame.event_type.startsWith('meeting_companion_') || !matchesMeeting(frame, meetingId)) return;
      wakeRetry?.();
      if (frame.event_type === 'meeting_companion_event') {
        dispatch({ type: 'event', event: frame.event as TimelineEvent });
      } else if (frame.event_type === 'meeting_companion_status') {
        const { event_type: _eventType, session_key: _sessionKey, meeting_ids: _meetingIds, ...status } = frame;
        dispatch({ type: 'status', status: status as unknown as Partial<CompanionStatus> });
      } else if (frame.event_type === 'meeting_companion_chat_delta') {
        const messageId = frame.message_id;
        const textDelta = frame.text_delta;
        if (typeof messageId === 'string' && typeof textDelta === 'string' && textDelta !== '') {
          dispatch({ type: 'chatDelta', messageId, textDelta });
        }
      }
    });
    socket.onConnect(() => {
      void hydrate();
    });
    socket.connect(companionSocketUrl(port));
    void hydrate();

    return () => {
      hydrationGeneration.current += 1;
      wakeRetry?.();
      socket.disconnect();
    };
  }, [meetingId, port]);

  useEffect(() => {
    if (state.resyncNeeded) void hydrateRef.current();
  }, [state.resyncNeeded]);

  const isLive = state.status.live;
  const isEnabled = state.status.live && state.status.enabled;

  useEffect(() => {
    if (!active || meetingId === null || !isEnabled) return;
    if ((state.status.model_id ?? null) === (selectedModelId ?? null)) return;
    void patchCompanionSettings(port, meetingId, { model_id: selectedModelId ?? null }).catch((error: unknown) => {
      setActionError(describeError(error));
    });
  }, [active, isEnabled, meetingId, port, selectedModelId, state.status.model_id]);

  // Sources queued before recording (or before the switch was on) attach once the live meeting's Companion is on, however it was turned on: this switch, the pane button, or auto-enable at the start of the recording.
  useEffect(() => {
    if (!isRecording || !isEnabled || meetingId === null || port <= 0 || pendingRoots.length === 0) return;
    const queued = pendingRoots;
    setPendingRoots([]);
    void (async () => {
      const failures: string[] = [];
      for (const path of queued) {
        try {
          await attachCompanionRoot(port, meetingId, path);
        } catch (error) {
          failures.push(describeError(error));
        }
      }
      if (failures.length > 0) setActionError(failures[0]);
    })();
  }, [isRecording, isEnabled, meetingId, pendingRoots, port]);

  const guarded = useCallback(
    async (operation: (currentMeetingId: string) => Promise<void>): Promise<boolean> => {
      if (meetingId === null || port <= 0) return false;
      setActionError(null);
      try {
        await operation(meetingId);
        return true;
      } catch (error) {
        setActionError(describeError(error));
        return false;
      }
    },
    [meetingId, port],
  );

  const enable = useCallback(
    () =>
      guarded(async (id) => {
        const snapshot = await enableCompanion(port, id, { model_id: selectedModelId ?? null });
        dispatch({ type: 'hydrated', snapshot });
      }),
    [guarded, port, selectedModelId],
  );

  const disable = useCallback(
    () =>
      guarded(async (id) => {
        const snapshot = await disableCompanion(port, id);
        dispatch({ type: 'hydrated', snapshot });
      }),
    [guarded, port],
  );

  const setMode = useCallback(
    (mode: CompanionMode) =>
      guarded(async (id) => {
        const status = await patchCompanionSettings(port, id, { mode });
        dispatch({ type: 'status', status });
      }),
    [guarded, port],
  );

  const setFocus = useCallback(
    (focus: string) =>
      guarded(async (id) => {
        const status = await patchCompanionSettings(port, id, { focus });
        dispatch({ type: 'status', status });
      }),
    [guarded, port],
  );

  const addRoots = useCallback(
    async (paths: string[]) => {
      const cleaned = Array.from(new Set(paths.map((path) => path.trim()).filter((path) => path !== '')));
      if (cleaned.length === 0) return;
      // Only a recording meeting whose Companion is off (the backend answers 409) and the pre-recording setup pane (no meeting yet) queue; a saved meeting attaches straight away.
      if (!isEnabled && (isRecordingRef.current || meetingId === null)) {
        setPendingRoots((current) => [...current, ...cleaned.filter((path) => !current.includes(path))]);
        return;
      }
      await guarded(async (id) => {
        for (const path of cleaned) {
          await attachCompanionRoot(port, id, path);
        }
      });
      // A meeting that is not being recorded has no live Companion stream, so its saved sources only reach the pane through a fresh snapshot (also after a partial failure, so the pane shows what did attach).
      if (!isRecordingRef.current) await hydrateRef.current();
    },
    [guarded, isEnabled, meetingId, port],
  );

  const removeRoot = useCallback(
    async (rootId: string) => {
      const removed = await guarded(async (id) => {
        await detachCompanionRoot(port, id, rootId);
      });
      // Re-read even when the removal failed so a stale row (for example a source another window already removed) disappears.
      if (!isRecordingRef.current) await hydrateRef.current();
      return removed;
    },
    [guarded, port],
  );

  const removePendingRoot = useCallback((path: string) => {
    setPendingRoots((current) => current.filter((entry) => entry !== path));
  }, []);

  const sendFeedback = useCallback(
    (itemId: string, action: CompanionFeedbackAction) =>
      guarded(async (id) => {
        await sendCompanionFeedback(port, id, itemId, action);
        // A finished meeting announces nothing, so reload to show the mark; without this the next click would send the same action again instead of clearing it.
        if (action.startsWith('audit_')) await hydrateRef.current();
      }),
    [guarded, port],
  );

  const sendChat = useCallback(
    (text: string) =>
      guarded(async (id) => {
        const accepted = await sendCompanionChat(port, id, text);
        dispatch({ type: 'chatPending', messageId: accepted.message_id });
      }),
    [guarded, port],
  );

  const createWatch = useCallback(
    (topic: string, instruction: string) =>
      guarded(async (id) => {
        await createCompanionWatch(port, id, topic, instruction);
      }),
    [guarded, port],
  );

  const cancelWatch = useCallback(
    (watchId: string) =>
      guarded(async (id) => {
        await cancelCompanionWatch(port, id, watchId);
      }),
    [guarded, port],
  );

  const decideProposal = useCallback(
    async (itemId: string, decision: CompanionProposalDecision): Promise<CompanionProposalResult | null> => {
      if (meetingId === null || port <= 0) return null;
      setActionError(null);
      try {
        const result = await decideCompanionProposal(port, meetingId, itemId, decision);
        dispatch({ type: 'proposalResult', itemId, result });
        return result;
      } catch (error) {
        setActionError(describeError(error));
        void hydrateRef.current();
        return null;
      }
    },
    [meetingId, port],
  );

  const runAudit = useCallback(
    () =>
      guarded(async (id) => {
        await startCompanionAudit(port, id);
      }),
    [guarded, port],
  );

  const actOnItem = useCallback(
    async (itemId: string, action: CompanionItemAction): Promise<CompanionItemActionResult | null> => {
      if (meetingId === null || port <= 0) return null;
      setActionError(null);
      try {
        const result = await actOnCompanionItem(port, meetingId, itemId, action);
        // A finished meeting has no live event stream, so the new action card only appears by refetching.
        void hydrateRef.current();
        return result;
      } catch (error) {
        setActionError(describeError(error));
        void hydrateRef.current();
        return null;
      }
    },
    [meetingId, port],
  );

  const investigate = useCallback(
    (question: string, replyToMessageId?: string) =>
      guarded(async (id) => {
        await startCompanionInvestigation(port, id, question, replyToMessageId);
      }),
    [guarded, port],
  );

  const stopInvestigations = useCallback(
    () =>
      guarded(async (id) => {
        for (const start of unresolvedInvestigations(state.timeline)) {
          try {
            await cancelCompanionInvestigation(port, id, start.id);
          } catch (error) {
            // A run that already ended answers 404; that is the outcome the user wanted.
            if (!(error instanceof CompanionApiError && error.status === 404)) throw error;
          }
        }
      }),
    [guarded, port, state.timeline],
  );

  const setInvestigate = useCallback(
    (enabled: boolean) =>
      guarded(async (id) => {
        const status = await patchCompanionSettings(port, id, { investigate: enabled });
        dispatch({ type: 'status', status });
      }),
    [guarded, port],
  );

  return {
    state,
    isLive,
    isEnabled,
    pendingRoots,
    actionError,
    clearActionError: () => setActionError(null),
    refresh: () => hydrateRef.current(),
    enable,
    disable,
    setMode,
    setFocus,
    addRoots,
    removeRoot,
    removePendingRoot,
    sendFeedback,
    sendChat,
    createWatch,
    cancelWatch,
    decideProposal,
    runAudit,
    actOnItem,
    investigate,
    stopInvestigations,
    setInvestigate,
  };
}
