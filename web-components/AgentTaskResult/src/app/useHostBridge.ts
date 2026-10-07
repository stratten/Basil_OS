import { useCallback, useEffect, useRef } from 'react';
import type { Dispatch, MutableRefObject, SetStateAction } from 'react';
import type {
  AgentStatus,
  CaptureStateMessage,
  DisplayableAgentTask,
  InitMessage,
  ValidationRunFocusRequest,
} from '../types';
import {
  registerCaptureHandler,
  registerInitHandler,
  registerNewAgentHandler,
  registerProvisionalTaskFailedHandler,
  registerRequestFollowUpHandler,
  registerShowExistingAgentTaskHandler,
  registerShowScheduledAgentTaskHandler,
  registerValidationRunFocusHandler,
  registerValidationManagedHistoryRestoreHandler,
  registerValidationRunStateRequestHandler,
  registerThemeHandler,
  registerDateStyleHandler,
  registerDetachedRootsHandler,
  reportResultWidgetReady,
  startFollowUpCapture,
} from '../services/bridge';
import { wsManager } from '../services/websocket';
import * as api from '../services/api';
import { agentStore } from '../store/agentStore';
import { hydrateActiveFollowUpChild, hydrateAgentFromBackend } from './agentHydration';
import { applyHostFonts, applyHostTheme } from './themeBootstrap';
import { applyHostDateStyle } from './dateDisplay';
import {
  buildDurableFollowUpHistoryBeforeActiveChild,
  buildFollowUpHistoryFromViewedDetail,
} from './followUpHistory';
import { DetachedAgentTaskScope } from './DetachedAgentTaskScope';
import { planDetachedInitHydration } from './detachedInitPlan';
import { mapDetailToDisplayable } from '../components/sidebar/sidebarUtils';

// Detached windows previously hydrated only the single root task id via
// hydrateAgentFromBackend, which reads status/result but drops
// detail.follow_ups entirely -- so a detached window for a follow-up chain
// showed just the first turn. The backend detail endpoint already returns
// the full chain (history_routes.py get_agent_task_details), so reuse the
// same mapDetailToDisplayable the main window's sidebar uses to seed the
// full agentTaskHistory here too.
export async function hydrateDetachedChain(rootTaskId: string): Promise<void> {
  try {
    const detail = await api.getAgentTaskDetail(rootTaskId);
    const displayable = mapDetailToDisplayable(detail);

    agentStore.setAgentTaskHistory(rootTaskId, displayable.agentTaskHistory);
    agentStore.updateAgentTaskTitle(rootTaskId, detail.title);
    agentStore.setDelegatedProviderReportCards(rootTaskId, displayable.delegatedProviderReportCards);

    const isTerminal = displayable.status === 'completed' || displayable.status === 'failed';
    if (isTerminal) {
      agentStore.updateAgentTaskText(rootTaskId, displayable.originalPrompt);
      agentStore.updateAgentDisplayPromptMarkdown(rootTaskId, displayable.displayPromptMarkdown);
      agentStore.setPresentationSummary(rootTaskId, displayable.presentationSummary);
      agentStore.setResult(rootTaskId, displayable.result, displayable.structuredFiles);
      agentStore.setReferencePaths(rootTaskId, displayable.referencePaths);
      agentStore.setResultOutcome(rootTaskId, displayable.outcome, displayable.resultSeverity);
      agentStore.setThinkingSegments(rootTaskId, displayable.thinkingSegments);
      if (displayable.executionTimeline.length > 0) {
        agentStore.setExecutionTimeline(rootTaskId, displayable.executionTimeline);
      }
      const finalStatus: 'completed' | 'failed' = displayable.status === 'failed' ? 'failed' : 'completed';
      agentStore.updateStatus(rootTaskId, finalStatus);
      if (displayable.isCanceled) {
        agentStore.markCanceled(rootTaskId);
      } else if (finalStatus === 'failed') {
        agentStore.setError(rootTaskId, displayable.errorMessage || displayable.result || 'Task failed');
      }
      return;
    }

    if (displayable.agentTaskId !== rootTaskId) {
      // The most recent turn is still in-flight. Wire it into the follow-up
      // mapping so live WS events for that child route to this root entry.
      agentStore.beginFollowUpTurn(displayable.agentTaskId, rootTaskId, undefined, displayable.previousTaskId);
      // beginFollowUpTurn snapshots the root's pre-hydration turn back into
      // history and blanks the current-turn fields. Re-seed the authoritative
      // prior turns (root + already-completed follow-ups) so the root card is
      // not duplicated, and restore the in-flight turn's own request text and
      // status so the chain renders as a clean conversation with the follow-up
      // as the current message -- not a second copy of the root prompt.
      agentStore.setAgentTaskHistory(rootTaskId, displayable.agentTaskHistory);
      agentStore.updateAgentTaskText(rootTaskId, displayable.originalPrompt);
      agentStore.updateAgentDisplayPromptMarkdown(rootTaskId, displayable.displayPromptMarkdown);
      agentStore.updateStatus(rootTaskId, displayable.status as AgentStatus);
      if (displayable.executionTimeline.length > 0) {
        agentStore.reconcileDurableArtifactTimeline(rootTaskId, displayable.executionTimeline);
      }
      // Reconcile the child's own status/result in case it finished between the
      // chain query and now. The child state is represented by this root entry.
      void hydrateActiveFollowUpChild(rootTaskId, displayable.agentTaskId);
      return;
    }

    hydrateAgentFromBackend(rootTaskId);
  } catch (error) {
    console.warn('[AgentTaskResult] Failed to hydrate detached chain; falling back to single-task hydration', rootTaskId, error);
    hydrateAgentFromBackend(rootTaskId);
  }
}

function hydrateDirectFollowUpHistory(
  rootTaskId: string,
  activeChildId: string,
  attempt = 0,
): void {
  void api.getAgentTaskDetail(rootTaskId)
    .then(detail => {
      if (agentStore.getCurrentTurnTaskId(rootTaskId) !== activeChildId) return;
      agentStore.setAgentTaskHistory(
        rootTaskId,
        buildDurableFollowUpHistoryBeforeActiveChild(detail, activeChildId),
      );
    })
    .catch(error => {
      if (attempt >= 2) {
        console.warn('[AgentTaskResult] Failed to hydrate durable follow-up history', {
          rootTaskId,
          activeChildId,
          error,
        });
        return;
      }
      window.setTimeout(
        () => hydrateDirectFollowUpHistory(rootTaskId, activeChildId, attempt + 1),
        600,
      );
    });
}

export interface MissedRunToast {
  runId: string;
  title: string;
  scheduledFor?: string;
  reason?: string;
}

interface UseHostBridgeArgs {
  setSidebarExpanded: Dispatch<SetStateAction<boolean>>;
  setCaptureState: Dispatch<SetStateAction<CaptureStateMessage | null>>;
  setInitialized: Dispatch<SetStateAction<boolean>>;
  setInitiallyProcessing: Dispatch<SetStateAction<boolean>>;
  setViewedDetail: Dispatch<SetStateAction<DisplayableAgentTask | null>>;
  setSelectedScheduledAgentTaskId: Dispatch<SetStateAction<string | null>>;
  setCreateScheduledMode: Dispatch<SetStateAction<boolean>>;
  setMissedRunToasts: Dispatch<SetStateAction<MissedRunToast[]>>;
  setDetachedRootTaskId: Dispatch<SetStateAction<string | null>>;
  setDetachedRootsElsewhere: Dispatch<SetStateAction<Set<string>>>;
  viewedDetailRef: MutableRefObject<DisplayableAgentTask | null>;
  onValidationRunStateRequest: (requestId: string) => void;
  onValidationRunFocus: (request: Required<ValidationRunFocusRequest>) => void;
  onValidationManagedHistoryRestore: (requestId: string) => void;
}

function applyInitialReferencePaths(agentTaskId: string, paths?: string[]) {
  const referencePaths = paths?.filter(path => path.trim().length > 0) ?? [];
  if (referencePaths.length > 0) {
    agentStore.setReferencePaths(agentTaskId, referencePaths);
  }
}

export function useHostBridge({
  setSidebarExpanded,
  setCaptureState,
  setInitialized,
  setInitiallyProcessing,
  setViewedDetail,
  setSelectedScheduledAgentTaskId,
  setCreateScheduledMode,
  setMissedRunToasts,
  setDetachedRootTaskId,
  setDetachedRootsElsewhere,
  viewedDetailRef,
  onValidationRunStateRequest,
  onValidationRunFocus,
  onValidationManagedHistoryRestore,
}: UseHostBridgeArgs): void {
  const detachedScopeRef = useRef<DetachedAgentTaskScope | null>(null);

  const handleInit = useCallback((config: InitMessage) => {
    api.setBaseUrl(config.port);

    if (config.theme) {
      applyHostTheme(config.theme);
    }

    if (config.fonts) {
      applyHostFonts(config.fonts);
    }

    applyHostDateStyle(config.dateDisplayStyle);
    detachedScopeRef.current = config.detachedRootTaskId
      ? new DetachedAgentTaskScope(config.detachedRootTaskId)
      : null;
    setDetachedRootTaskId(config.detachedRootTaskId || null);

    if (config.initialSidebarExpanded) {
      setSidebarExpanded(true);
    }

    if (config.initiallyProcessing) {
      setInitiallyProcessing(true);
    }

    if (config.initialAgentTaskId) {
      agentStore.registerAgent(config.initialAgentTaskId, config.initialAgentTask);
      applyInitialReferencePaths(config.initialAgentTaskId, config.initialReferencePaths);
      if (config.initiallyProcessing) {
        agentStore.markTransientAgent(config.initialAgentTaskId);
      }
      agentStore.updateStatus(config.initialAgentTaskId, 'processing');
      if (!config.initialAgentTask) {
        agentStore.updateProgressStep(config.initialAgentTaskId, 'Transcribing audio', true, false);
        agentStore.updateStep(config.initialAgentTaskId, 'Transcribing audio');
      }
      agentStore.selectAgent(config.initialAgentTaskId);
    }

    // The detached-window hydration rules live in a pure helper so they can be
    // unit-tested directly (see detachedInitPlan.ts / .test.ts).
    const hydrationPlan = planDetachedInitHydration(config);

    // Self-hydrate the initial task only for non-detached windows; a detached
    // window lets hydrateDetachedChain own reconciliation of the whole thread.
    if (hydrationPlan.selfHydrateInitialTaskId) {
      const cmdId = hydrationPlan.selfHydrateInitialTaskId;
      wsManager.onConnect(() => {
        hydrateAgentFromBackend(cmdId);
      });
    }

    // Detached windows always load the full chain onto the root entry so the
    // popped-out window shows every turn -- even a fully terminal multi-turn
    // chain, and even when the host passes the same id for the initial task
    // and the chain root.
    if (hydrationPlan.hydrateChainRootId) {
      agentStore.registerAgent(hydrationPlan.hydrateChainRootId);
      agentStore.selectAgent(hydrationPlan.hydrateChainRootId);
      void hydrateDetachedChain(hydrationPlan.hydrateChainRootId);
    }

    wsManager.connect(config.wsUrl);
    setInitialized(true);
    reportResultWidgetReady();
  }, [setDetachedRootTaskId, setInitialized, setInitiallyProcessing, setSidebarExpanded]);

  useEffect(() => {
    registerInitHandler(handleInit);
    registerCaptureHandler(setCaptureState);
    registerThemeHandler((theme, fonts) => {
      applyHostTheme(theme);
      applyHostFonts(fonts);
    });
    registerDateStyleHandler((style) => {
      applyHostDateStyle(style);
    });
    registerDetachedRootsHandler((rootTaskIds) => {
      setDetachedRootsElsewhere(new Set(rootTaskIds));
    });

    registerRequestFollowUpHandler(() => {
      const id = agentStore.getSelectedAgentId();
      if (id) {
        const agent = agentStore.getAgent(id);
        const parentId = agent?.rootTaskId || id;
        const previousTaskId = agentStore.getCurrentTurnTaskId(parentId);
        agentStore.setPendingFollowUpParent(parentId);
        startFollowUpCapture(parentId, previousTaskId);
      } else if (viewedDetailRef.current) {
        const detail = viewedDetailRef.current;
        const parentId = detail.rootTaskId || detail.agentTaskId;
        agentStore.setPendingFollowUpParent(parentId);
        startFollowUpCapture(parentId, detail.currentTurnTaskId || detail.agentTaskId);
      }
    });

    registerShowExistingAgentTaskHandler((agentTaskId) => {
      const alreadyKnown = !!agentStore.getAgent(agentTaskId);
      if (!alreadyKnown) {
        agentStore.registerAgent(agentTaskId);
        agentStore.updateStatus(agentTaskId, 'processing');
      }
      setViewedDetail(null);
      setSelectedScheduledAgentTaskId(null);
      setCreateScheduledMode(false);
      agentStore.selectAgent(agentTaskId);
      hydrateAgentFromBackend(agentTaskId);
    });

    registerShowScheduledAgentTaskHandler((scheduledAgentTaskId) => {
      agentStore.deselectAgent();
      setViewedDetail(null);
      setCreateScheduledMode(false);
      setSelectedScheduledAgentTaskId(scheduledAgentTaskId);
    });
    const unregisterValidationRunStateRequest = registerValidationRunStateRequestHandler(
      onValidationRunStateRequest,
    );
    const unregisterValidationRunFocus = registerValidationRunFocusHandler(onValidationRunFocus);
    const unregisterValidationManagedHistoryRestore = registerValidationManagedHistoryRestoreHandler(
      onValidationManagedHistoryRestore,
    );

    registerNewAgentHandler((data) => {
      if (agentStore.isFollowUp(data.agentTaskId)) return;
      const pendingParent = agentStore.consumePendingFollowUpParent();
      const parentId = data.rootTaskId ?? pendingParent ?? null;
      if (parentId) {
        const parentAgent = agentStore.getAgent(parentId);
        let beganFollowUpTurn = false;
        if (parentAgent) {
          agentStore.beginFollowUpTurn(data.agentTaskId, parentId, undefined, data.previousTaskId);
          beganFollowUpTurn = true;
        } else if (viewedDetailRef.current) {
          const detail = viewedDetailRef.current;
          const detailId = detail.rootTaskId || detail.agentTaskId;
          if (detailId === parentId) {
            const completeHistory = buildFollowUpHistoryFromViewedDetail(detail);
            const snapshot = completeHistory[completeHistory.length - 1];
            agentStore.beginFollowUpTurn(data.agentTaskId, parentId, snapshot, data.previousTaskId);
            agentStore.setAgentTaskHistory(parentId, completeHistory);
            beganFollowUpTurn = true;
          }
        }
        if (!beganFollowUpTurn) {
          agentStore.beginFollowUpTurn(data.agentTaskId, parentId, undefined, data.previousTaskId);
        }
        hydrateDirectFollowUpHistory(parentId, data.agentTaskId);
        applyInitialReferencePaths(data.agentTaskId, data.referencePaths);
        return;
      }
      agentStore.registerAgent(data.agentTaskId);
      applyInitialReferencePaths(data.agentTaskId, data.referencePaths);
      agentStore.markTransientAgent(data.agentTaskId);
      agentStore.updateStatus(data.agentTaskId, 'processing');
      agentStore.selectAgent(data.agentTaskId);
    });

    registerProvisionalTaskFailedHandler((payload) => {
      console.log(
        `[AgentTaskResult] Provisional task failed (bridge): ${payload.agentTaskId} reason=${payload.reason} message=${payload.message}`
      );
      agentStore.handleProvisionalFailure(payload.agentTaskId, payload.message);
    });

    const unsubscribe = wsManager.subscribe(event => {
      if (detachedScopeRef.current && !detachedScopeRef.current.admits(event)) {
        return;
      }
      agentStore.handleWSEvent(event);

      if (event.event_type === 'agent_task_provisional_failed') {
        const provisionalId = (event.agent_task_id as string | undefined) || '';
        if (provisionalId) {
          const message = (event.message as string | undefined)
            ?? 'Audio could not be processed.';
          console.log(
            `[AgentTaskResult] Provisional task failed (ws): ${provisionalId} message=${message}`
          );
          agentStore.handleProvisionalFailure(provisionalId, message);
        }
      }

      if (event.event_type === 'scheduled_agent_task_missed') {
        const runId = (event.run_id as string) || crypto.randomUUID();
        const title = (event.title as string) || 'Scheduled task';
        const scheduledFor = (event.scheduled_for as string | undefined);
        const reason = (event.reason as string | undefined);
        setMissedRunToasts(prev => [
          ...prev.filter(t => t.runId !== runId),
          { runId, title, scheduledFor, reason },
        ]);
        setTimeout(() => {
          setMissedRunToasts(current => current.filter(t => t.runId !== runId));
        }, 8000);
      }
    });

    return () => {
      unsubscribe();
      wsManager.disconnect();
      unregisterValidationRunStateRequest();
      unregisterValidationRunFocus();
      unregisterValidationManagedHistoryRestore();
    };
  }, [
    handleInit,
    setCaptureState,
    setCreateScheduledMode,
    setMissedRunToasts,
    setSelectedScheduledAgentTaskId,
    setDetachedRootsElsewhere,
    setViewedDetail,
    viewedDetailRef,
    onValidationRunFocus,
    onValidationManagedHistoryRestore,
    onValidationRunStateRequest,
  ]);
}

