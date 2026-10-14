import { useCallback, useEffect, useReducer, useRef, useState } from 'react';
import { ReconnectingWebSocket } from '@shared/websocket/reconnectingWebSocket';
import {
  CompanionApiError,
  attachCompanionRoot,
  cancelCompanionWatch,
  companionSocketUrl,
  createCompanionWatch,
  detachCompanionRoot,
  disableCompanion,
  enableCompanion,
  fetchSnapshot,
  patchCompanionSettings,
  sendCompanionChat,
  sendCompanionFeedback,
} from './companionApi';
import { companionStoreReducer, initialCompanionStoreState, type CompanionStoreState } from './companionStore';
import type {
  CompanionFeedbackAction,
  CompanionMode,
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
}

function describeError(error: unknown): string {
  if (error instanceof CompanionApiError) return error.message;
  return error instanceof Error ? error.message : 'Something went wrong.';
}

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
    const isCurrent = () => hydrationGeneration.current === generation;

    const hydrate = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const snapshot = await fetchSnapshot(port, meetingId);
        if (isCurrent()) dispatch({ type: 'hydrated', snapshot });
      } catch (error) {
        if (isCurrent()) dispatch({ type: 'loadFailed', message: describeError(error) });
      } finally {
        inFlight = false;
      }
    };
    hydrateRef.current = hydrate;

    const socket = new ReconnectingWebSocket<CompanionSocketEvent>({ logLabel: '[Companion WS]' });
    socket.subscribe((frame) => {
      if (!isCurrent() || !frame.event_type.startsWith('meeting_companion_') || !matchesMeeting(frame, meetingId)) return;
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
      if (!isEnabled) {
        setPendingRoots((current) => [...current, ...cleaned.filter((path) => !current.includes(path))]);
        return;
      }
      await guarded(async (id) => {
        for (const path of cleaned) {
          await attachCompanionRoot(port, id, path);
        }
      });
    },
    [guarded, isEnabled, port],
  );

  const removeRoot = useCallback(
    (rootId: string) =>
      guarded(async (id) => {
        await detachCompanionRoot(port, id, rootId);
      }),
    [guarded, port],
  );

  const removePendingRoot = useCallback((path: string) => {
    setPendingRoots((current) => current.filter((entry) => entry !== path));
  }, []);

  const sendFeedback = useCallback(
    (itemId: string, action: CompanionFeedbackAction) =>
      guarded(async (id) => {
        await sendCompanionFeedback(port, id, itemId, action);
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
  };
}
