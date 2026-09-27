import { useCallback, useEffect, useRef, useState } from 'react';
import type { Dispatch, RefObject, SetStateAction } from 'react';
import type { AgentState, DisplayableAgentTask } from '../types';
import { reportWidgetHeaderHeight, requestResize } from '../services/bridge';
import { agentStore } from '../store/agentStore';
import { isInFlightAgentStatus } from './agentHydration';
import { measureCollapsedHeaderSize } from './collapsedHeaderSizing';
import { measureExpandedWidgetContentHeight, measureOverlayDialogIntrinsicHeight } from './resultWidgetSizing';
import { WEBKIT_WINDOW_CHROME_FRAME_INSET_PX } from '../../../shared/webkitWindowChrome';
import {
  clampDetailTrayWidth,
  detailTrayPreferredWidth,
  standaloneMinimumWidth,
  type DetailTrayMode,
} from './detailTraySizing';

interface UseResultWidgetSizingArgs {
  displaySource: DisplayableAgentTask | null;
  selectedAgent: AgentState | null;
  viewedDetail: DisplayableAgentTask | null;
  sidebarExpanded: boolean;
  embedded: boolean;
  contentSurfaceMode?: 'agent' | 'detached' | 'empty' | 'scheduled';
  contentSurfaceId?: string | null;
  textFollowUpMode?: boolean;
  isCapturing?: boolean;
  initialized?: boolean;
  initiallyProcessing?: boolean;
}

interface UseResultWidgetSizingResult {
  rootRef: RefObject<HTMLDivElement>;
  sidebarWidth: number;
  detailTrayWidth: number;
  detailTrayOpen: boolean;
  detailTrayMode: DetailTrayMode;
  setDetailTrayOpen: Dispatch<SetStateAction<boolean>>;
  openDetailTray: (mode: DetailTrayMode) => void;
  setDetailTrayMode: (mode: DetailTrayMode) => void;
  setDetailTrayWidth: (width: number) => void;
  isChromeCollapsed: boolean;
  isCollapseIconRotated: boolean;
  handleToggleChromeCollapsed: () => void;
  expandChrome: () => void;
  /**
   * Notifies this hook that a live drag on the detail tray's own resize
   * handle is in progress, so the native-window-resize effect below can
   * suppress `requestResize` for the duration of the drag. An animated
   * `NSWindow.setFrame` mid-drag (from `WindowChromeCollapse.applyFrame`)
   * steals the OS-level mouse-tracking loop that WebKit's pointer capture
   * depends on, which produced the "tray collapses on the first resize
   * drag" symptom: widening the tray even slightly changes
   * `standaloneMinimumWidth`, which fired a live, animated window resize
   * while the resize handle still held pointer capture.
   */
  setTrayResizing: (isResizing: boolean) => void;
}

function logResizeTrace(event: string, payload: Record<string, unknown>): void {
  console.log(`[AgentTaskResult][${event}] ${JSON.stringify(payload)}`);
}

// Both the approval card (`ApprovalOverlay.tsx`) and the checkpoint dialog
// (`AgentTaskInputSurface.tsx`) mark their own root with this attribute pair
// so this hook can measure "the thing the user is actually being asked to
// look at" directly, instead of inferring a width/height from `AgentState`
// flags (which drift from the overlay's real markup, and say nothing about
// intrinsic height at all) or from a stale pre-collapse frame that predates
// the interaction ever existing.
const INTERACTIVE_OVERLAY_SELECTOR = '[data-agent-desk-interactive-overlay="true"]';

interface InteractiveOverlayTarget {
  width: number;
  height: number;
}

function isInteractiveOverlayElementVisible(element: HTMLElement): boolean {
  return element.closest('[aria-hidden="true"], [inert]') === null;
}

// Approval and checkpoint overlays are absolutely positioned over the
// content pane, so their own `offsetHeight`/`scrollHeight` is the content's
// real intrinsic size, but their *width* is normally clamped by the current
// (possibly collapsed-then-still-narrow) window rather than reflecting what
// the content actually wants. `data-preferred-content-width` carries that
// intent explicitly rather than this hook guessing it from `AgentState`.
function measureInteractiveOverlayTarget(): InteractiveOverlayTarget | null {
  const elements = Array.from(
    document.querySelectorAll<HTMLElement>(INTERACTIVE_OVERLAY_SELECTOR),
  ).filter(isInteractiveOverlayElementVisible);

  if (elements.length === 0) {
    return null;
  }

  let totalHeight = 0;
  let maxWidth = 0;
  for (const element of elements) {
    totalHeight += Math.max(element.offsetHeight || 0, element.scrollHeight || 0, 0);
    const preferredWidthAttr = Number.parseFloat(element.getAttribute('data-preferred-content-width') || '');
    const preferredWidth = Number.isFinite(preferredWidthAttr) ? preferredWidthAttr : (element.offsetWidth || 0);
    maxWidth = Math.max(maxWidth, preferredWidth);
  }

  if (totalHeight <= 0 && maxWidth <= 0) {
    return null;
  }

  return { width: maxWidth, height: totalHeight };
}

export function useResultWidgetSizing({
  displaySource,
  selectedAgent,
  viewedDetail,
  sidebarExpanded,
  embedded,
  contentSurfaceMode = 'agent',
  contentSurfaceId = null,
  textFollowUpMode = false,
  isCapturing = false,
  initialized = false,
  initiallyProcessing = false,
}: UseResultWidgetSizingArgs): UseResultWidgetSizingResult {
  const rootRef = useRef<HTMLDivElement>(null);
  const [detailTrayOpen, setDetailTrayOpen] = useState(false);
  const [detailTrayMode, setDetailTrayModeState] = useState<DetailTrayMode>('overview');
  const [configuredDetailTrayWidth, setConfiguredDetailTrayWidth] = useState(detailTrayPreferredWidth('overview'));
  const [isDetailTrayWidthUserControlled, setIsDetailTrayWidthUserControlled] = useState(false);
  const [isChromeCollapsed, setIsChromeCollapsed] = useState(false);
  const [isCollapseIconRotated, setIsCollapseIconRotated] = useState(false);
  const lastRequestedSize = useRef({ width: 320, height: 180 });
  const lastResizeTime = useRef(0);
  const pendingResizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingResizeAnimationFrame = useRef<number | null>(null);
  const lastSelectedIdRef = useRef<string | null>(null);
  const skipResizeRef = useRef(false);
  const expandedSizeBeforeCollapseRef = useRef<{ width: number; height: number } | null>(null);
  const preserveExpandedWidthRef = useRef<number | null>(null);
  const prevNeedsInputRef = useRef(false);
  const previousLayoutRef = useRef({ sidebarExpanded, detailTrayOpen: false });
  const isTrayResizingRef = useRef(false);
  const scheduleMeasurementRef = useRef<() => void>(() => {});

  const setTrayResizing = useCallback((isResizing: boolean) => {
    const wasResizing = isTrayResizingRef.current;
    isTrayResizingRef.current = isResizing;
    // TEMPORARY DIAGNOSTIC LOGGING: confirming whether the drag-suppression
    // flag is actually engaged for the full pointerdown-to-pointerup span,
    // and whether any native resize still slips through while it's active.
    // Remove once the "still collapses while dragging" report is resolved.
    logResizeTrace('setTrayResizing', { wasResizing, isResizing });
    if (wasResizing && !isResizing) {
      // The drag just ended: run the measurement we suppressed during the
      // drag once now, so the window catches up to the settled tray width
      // without ever animating a native resize while pointer capture was
      // still held on the resize handle.
      scheduleMeasurementRef.current();
    }
  }, []);

  const displayRootTaskId = displaySource?.rootTaskId || displaySource?.agentTaskId;

  useEffect(() => {
    setIsChromeCollapsed(false);
    setIsCollapseIconRotated(false);
    expandedSizeBeforeCollapseRef.current = null;
    preserveExpandedWidthRef.current = null;
  }, [displayRootTaskId]);

  const sidebarWidth = sidebarExpanded ? 220 : 28;
  const detailTrayWidth = detailTrayOpen ? configuredDetailTrayWidth : 0;
  const layoutMinimumWidth = standaloneMinimumWidth(sidebarExpanded, detailTrayOpen ? detailTrayWidth : undefined);
  const applyDetailTrayMode = useCallback((mode: DetailTrayMode) => {
    setDetailTrayModeState(mode);
    if (!isDetailTrayWidthUserControlled) {
      setConfiguredDetailTrayWidth(detailTrayPreferredWidth(mode));
    }
  }, [isDetailTrayWidthUserControlled]);
  const setDetailTrayMode = useCallback((mode: DetailTrayMode) => {
    applyDetailTrayMode(mode);
  }, [applyDetailTrayMode]);
  const openDetailTray = useCallback((mode: DetailTrayMode) => {
    skipResizeRef.current = false;
    applyDetailTrayMode(mode);
    setDetailTrayOpen(true);
  }, [applyDetailTrayMode]);
  const setDetailTrayWidth = useCallback((width: number) => {
    setIsDetailTrayWidthUserControlled(true);
    setConfiguredDetailTrayWidth(clampDetailTrayWidth(width));
  }, []);

  const sizingAgent = selectedAgent ?? viewedDetail;
  const sizingSignature = [
    sizingAgent?.agentTaskId ?? '',
    displaySource?.agentTaskId ?? '',
    String(displaySource?.isStreaming ?? false),
    displaySource?.status ?? '',
    String(Boolean(sizingAgent?.result)),
    String(Boolean(sizingAgent?.errorMessage)),
    String(Boolean(sizingAgent?.showWorkflowPlan && sizingAgent?.workflowPlan)),
    String(sizingAgent?.agentTaskHistory.length ?? 0),
    String(Boolean(selectedAgent?.showApprovalPrompt)),
    selectedAgent?.inlineCheckpoint?.checkpoint_id ?? '',
    String(Boolean(selectedAgent?.showCheckpointPrompt)),
    String(sidebarWidth),
    String(detailTrayWidth),
    String(detailTrayOpen),
    String(layoutMinimumWidth),
    detailTrayMode,
    String(isChromeCollapsed),
    contentSurfaceMode,
    contentSurfaceId ?? '',
    String(textFollowUpMode),
    String(isCapturing),
    String(initialized),
    String(initiallyProcessing),
  ].join('|');

  // Measure laid-out flex children in the content pane. Using
  // `.main-content` scrollHeight would treat internally scrolled reasoning
  // as new outer height and resize the host window on every thinking update.
  useEffect(() => {
    if (embedded) {
      return;
    }

    const currentId = agentStore.getSelectedAgentId() || viewedDetail?.agentTaskId || null;
    const idChanged = currentId !== lastSelectedIdRef.current;
    lastSelectedIdRef.current = currentId;

    const isActive = displaySource?.isStreaming || isInFlightAgentStatus(displaySource?.status);
    const collapsedRailMinimumWidth = displaySource
      ? standaloneMinimumWidth(sidebarExpanded)
      : 0;

    if (idChanged && !isActive) {
      skipResizeRef.current = true;
    }
    if (isActive) {
      skipResizeRef.current = false;
    }

    // Correct the native drag-area overlay's height unconditionally, even
    // when the window-resize measurement below is about to be skipped (e.g.
    // a completed task selected for the first time). Otherwise the drag
    // strip keeps its pre-layout 44px guess until some *other* change --
    // like opening the detail tray -- happens to clear the skip further
    // down. A user who grabs the tray's resize handle immediately after
    // that first open still races the bridge round-trip and usually loses:
    // their mousedown lands on the still-guessed-height drag strip, which
    // starts a native window drag instead of reaching the resize handle's
    // own pointer handler, so the tray appears to "collapse" rather than
    // resize. Reporting the height here, ahead of the skip return, means
    // the correction is already in flight from the very first render.
    if (!isChromeCollapsed) {
      const earlyHeader = document.querySelector('.widget-header') as HTMLElement | null;
      if (earlyHeader) {
        reportWidgetHeaderHeight(earlyHeader.offsetHeight);
      }
    }

    // Opening history is an empty, browse-only surface: the expanded
    // sidebar is rendered inside the fixed 444px history window, but it is
    // not a request to resize that window. Defer all automatic sizing until
    // a task, scheduled-task surface, or explicit accessory has been
    // selected by the user. This deferral must not apply once the user has
    // explicitly collapsed the chrome, though -- otherwise collapsing before
    // ever selecting a task hides `.widget-body` (which already collapses
    // unconditionally, independent of `displaySource`) while leaving the
    // native window at its prior, uncollapsed frame, producing a header-only
    // strip sitting atop a large blank remainder of the window.
    if (!displaySource && contentSurfaceMode === 'empty' && !isChromeCollapsed) {
      previousLayoutRef.current = { sidebarExpanded, detailTrayOpen };
      return;
    }

    const layoutChangedWhileResizeSkipped = previousLayoutRef.current.sidebarExpanded !== sidebarExpanded
      || previousLayoutRef.current.detailTrayOpen !== detailTrayOpen;
    if (skipResizeRef.current && !isChromeCollapsed && window.innerWidth >= collapsedRailMinimumWidth) {
      if (layoutChangedWhileResizeSkipped) {
        // Skipping automatic content measurement must not leave Swift enforcing
        // a minimum width from a now-closed sidebar or tray. Reconcile only
        // the constraint using the current frame as the requested size: this
        // preserves the visible widget dimensions and merely lets the user
        // manually resize below the stale accessory width afterward.
        const currentSize = {
          width: window.innerWidth,
          height: window.innerHeight,
        };
        previousLayoutRef.current = { sidebarExpanded, detailTrayOpen };
        lastRequestedSize.current = currentSize;
        logResizeTrace('resize skipped layout constraint reconciliation', {
          currentId,
          ...currentSize,
          layoutMinimumWidth,
        });
        requestResize(currentSize.width, currentSize.height, 'layout', layoutMinimumWidth);
      }
      logResizeTrace('resize skipped measurement', {
        currentId,
        isChromeCollapsed,
        windowWidth: window.innerWidth,
        windowHeight: window.innerHeight,
        lastRequestedSize: lastRequestedSize.current,
      });
      return;
    }

    const measureAndResize = () => {
      if (isTrayResizingRef.current) {
        // A live drag on the detail tray's resize handle is in progress.
        // Skip the native resize entirely rather than firing an animated
        // `NSWindow.setFrame` mid-gesture -- see `setTrayResizing`'s doc
        // comment above for why that steals WebKit's pointer capture.
        // `setTrayResizing` re-runs this measurement once the drag ends.
        logResizeTrace('resize measurement suppressed (tray resize drag active)', {
          windowWidth: window.innerWidth,
          windowHeight: window.innerHeight,
        });
        return;
      }

      const contentArea = document.querySelector('.content-area') as HTMLElement | null;
      const mainContent = document.querySelector('.main-content') as HTMLElement | null;
      const header = document.querySelector('.widget-header') as HTMLElement | null;

      const headerH = header?.offsetHeight ?? 52;
      // The native window-drag overlay (`WindowDragAreaView`) is sized from
      // a pre-layout guess until this measurement corrects it; otherwise a
      // shorter-than-guessed header lets the drag strip bleed into the
      // sidebar's own header row and swallow clicks on its toggle button.
      if (!isChromeCollapsed && header) {
        reportWidgetHeaderHeight(headerH);
      }
      if (isChromeCollapsed) {
        const compactSize = measureCollapsedHeaderSize(header);
        const targetW = compactSize.width;
        const targetH = compactSize.height;
        logResizeTrace('resize collapsed request', {
          headerH,
          targetW,
          targetH,
          windowWidth: window.innerWidth,
          windowHeight: window.innerHeight,
          expandedSizeBeforeCollapse: expandedSizeBeforeCollapseRef.current,
          lastRequestedSize: lastRequestedSize.current,
        });
        lastRequestedSize.current = { width: targetW, height: targetH };
        requestResize(targetW, targetH, 'collapsed');
        return;
      }

      const contentH = measureExpandedWidgetContentHeight({ contentArea, mainContent });
      const activeDialog = document.querySelector('.agent-task-input-dialog') as HTMLElement | null;
      const backdrop = activeDialog?.closest('.agent-task-input-backdrop');
      const backdropStyle = backdrop instanceof HTMLElement ? getComputedStyle(backdrop) : null;
      const backdropVerticalInset = (Number.parseFloat(backdropStyle?.paddingTop ?? '') || 0)
        + (Number.parseFloat(backdropStyle?.paddingBottom ?? '') || 0);
      const overlayContentH = measureOverlayDialogIntrinsicHeight(activeDialog) + backdropVerticalInset;
      const interactiveOverlayTarget = measureInteractiveOverlayTarget();

      const rootPadding = WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2;
      const desiredH = headerH
        + Math.max(contentH, overlayContentH, interactiveOverlayTarget?.height ?? 0)
        + rootPadding;

      const minH = 180;
      const maxH = 700;
      const targetH = Math.min(Math.max(desiredH, minH), maxH);

      const sw = sidebarWidth;
      let targetW: number;
      const ds = selectedAgent ?? viewedDetail;
      if (ds) {
        const hasResult = !!ds.result;
        const hasError = !!ds.errorMessage;
        const hasWorkflow = !!ds.showWorkflowPlan && !!ds.workflowPlan;
        const hasHistory = ds.agentTaskHistory.length > 0;
        const agentProcessing = isInFlightAgentStatus(ds.status);

        if (selectedAgent?.showApprovalPrompt) {
          targetW = 480 + sw;
        } else if ((hasResult || hasError) && hasWorkflow) {
          targetW = 560 + sw;
        } else if (hasResult || hasError) {
          targetW = 560 + sw;
        } else if (hasWorkflow) {
          targetW = 480 + sw;
        } else if (agentProcessing && hasHistory) {
          targetW = 560 + sw;
        } else if (agentProcessing) {
          targetW = 320 + sw;
        } else {
          targetW = 320 + sw;
        }
      } else {
        targetW = 320 + sw;
      }

      // The active approval/checkpoint overlay's own preferred width is the
      // sizing authority whenever it's visible: it reflects what that
      // specific interaction actually needs (e.g. a wide AppleScript
      // approval, or a checkpoint dialog with a multi-field provider form),
      // not a generic guess derived from which `AgentState` flags happen to
      // be set.
      if (interactiveOverlayTarget) {
        targetW = Math.max(targetW, interactiveOverlayTarget.width + sw);
      }

      if (detailTrayOpen) {
        targetW = Math.max(
          targetW,
          standaloneMinimumWidth(sidebarExpanded, detailTrayWidth),
        );
      } else if (displaySource) {
        targetW = Math.max(
          targetW,
          standaloneMinimumWidth(sidebarExpanded),
        );
      }

      const currentW = Math.max(lastRequestedSize.current.width, window.innerWidth);
      // Use the larger of our tracked height and the actual window height,
      // so we never shrink below a size the user manually dragged to.
      const actualH = window.innerHeight;
      const currentH = Math.max(lastRequestedSize.current.height, actualH);

      const previousLayout = previousLayoutRef.current;
      const layoutChanged = previousLayout.sidebarExpanded !== sidebarExpanded
        || previousLayout.detailTrayOpen !== detailTrayOpen;
      // TEMPORARY DIAGNOSTIC LOGGING: capturing the layout-change inputs on
      // every measurement pass, to catch the "history item shows at the
      // right size, then resizes as though the sidebar were expanded" case
      // -- i.e. layoutChanged reads true on a render where the user never
      // touched the sidebar or tray toggle. Remove once root-caused.
      logResizeTrace('layout snapshot', {
        currentId,
        sidebarExpanded,
        detailTrayOpen,
        previousSidebarExpanded: previousLayout.sidebarExpanded,
        previousDetailTrayOpen: previousLayout.detailTrayOpen,
        layoutChanged,
        windowWidth: window.innerWidth,
      });
      // Interior changes may retain the existing frame or grow it, but never
      // reduce it. Closing either sidebar is an interior-layout update, not
      // an instruction to contract the result window; only an explicit user
      // chrome-collapse or manual window resize may make the window smaller.
      if (layoutChanged) {
        targetW = Math.max(targetW, window.innerWidth, layoutMinimumWidth);
      }
      previousLayoutRef.current = { sidebarExpanded, detailTrayOpen };

      const hChanged = targetH > currentH && targetH - currentH > 4;
      const preservedWidth = preserveExpandedWidthRef.current;
      const effectiveTargetW = preservedWidth ?? targetW;
      const wChanged = effectiveTargetW > currentW && effectiveTargetW - currentW > 2;

      if (layoutChanged || hChanged || wChanged) {
        const newW = wChanged ? effectiveTargetW : currentW;
        const newH = hChanged ? targetH : currentH;
        logResizeTrace('resize expanded request', {
          newW,
          newH,
          reason: { hChanged, wChanged },
        });
        lastRequestedSize.current = { width: newW, height: newH };
        requestResize(newW, newH, layoutChanged ? 'layout' : 'content', layoutMinimumWidth);
      }
    };

    const scheduleMeasurement = () => {
      if (pendingResizeAnimationFrame.current !== null || pendingResizeTimer.current) {
        return;
      }

      const now = Date.now();
      const elapsed = now - lastResizeTime.current;
      const throttleMs = 300;
      const requestMeasurement = () => {
        pendingResizeAnimationFrame.current = requestAnimationFrame(() => {
          pendingResizeAnimationFrame.current = null;
          measureAndResize();
        });
      };

      if (elapsed >= throttleMs) {
        lastResizeTime.current = now;
        requestMeasurement();
        return;
      }

      const delay = throttleMs - elapsed;
      pendingResizeTimer.current = setTimeout(() => {
        lastResizeTime.current = Date.now();
        pendingResizeTimer.current = null;
        requestMeasurement();
      }, delay);
    };

    scheduleMeasurementRef.current = scheduleMeasurement;

    const contentArea = document.querySelector('.content-area') as HTMLElement | null;
    const mainContent = document.querySelector('.main-content') as HTMLElement | null;
    const header = document.querySelector('.widget-header') as HTMLElement | null;
    const dialog = document.querySelector('.agent-task-input-dialog') as HTMLElement | null;
    const resizeObserver = typeof ResizeObserver === 'undefined'
      ? null
      : new ResizeObserver(scheduleMeasurement);

    if (contentArea) {
      resizeObserver?.observe(contentArea);
    }
    if (mainContent) {
      resizeObserver?.observe(mainContent);
    }
    if (header) {
      resizeObserver?.observe(header);
    }
    if (dialog) {
      resizeObserver?.observe(dialog);
    }

    scheduleMeasurement();

    return () => {
      resizeObserver?.disconnect();
      if (pendingResizeAnimationFrame.current !== null) {
        cancelAnimationFrame(pendingResizeAnimationFrame.current);
        pendingResizeAnimationFrame.current = null;
      }
      if (pendingResizeTimer.current) {
        clearTimeout(pendingResizeTimer.current);
        pendingResizeTimer.current = null;
      }
    };
  }, [embedded, sizingSignature]);

  const collapseChrome = useCallback(() => {
    skipResizeRef.current = false;

    const currentExpandedSize = {
      width: window.innerWidth,
      height: window.innerHeight,
    };
    logResizeTrace('collapse collapsing', {
      currentExpandedSize,
      lastRequestedSize: lastRequestedSize.current,
      expandedSizeBeforeCollapse: expandedSizeBeforeCollapseRef.current,
    });
    expandedSizeBeforeCollapseRef.current = currentExpandedSize;
    preserveExpandedWidthRef.current = currentExpandedSize.width;
    lastRequestedSize.current = {
      width: currentExpandedSize.width,
      height: 0,
    };
    // detailTrayOpen is deliberately left untouched here. The compact window
    // has no room to lay the tray out, but ExecutionDetailTray only unmounts
    // when its own isOpen prop is false (see ExecutionDetailTray.tsx's early
    // `if (!isOpen) return null`), and widget-body's `hidden`/`inert`
    // attributes already fully suppress its visibility and interactivity
    // while collapsed (see AgentTaskResultBody.tsx). Forcing detailTrayOpen
    // to false here would unmount the tray's contents -- discarding not just
    // "was it open" but *what* was open (the selected artifact preview, the
    // run overview toggle, etc., all local state inside
    // AgentTaskDetailSurface) -- for a visual constraint that hiding the
    // whole body already satisfies on its own.
    setIsCollapseIconRotated(true);
    requestAnimationFrame(() => {
      setIsChromeCollapsed(true);
    });
  }, []);

  const expandChrome = useCallback(() => {
    skipResizeRef.current = false;
    setIsCollapseIconRotated(false);
    if (expandedSizeBeforeCollapseRef.current) {
      const expandedSize = expandedSizeBeforeCollapseRef.current;
      logResizeTrace('collapse expanding start', {
        expandedSize,
        currentWindowWidth: window.innerWidth,
        currentWindowHeight: window.innerHeight,
        lastRequestedSize: lastRequestedSize.current,
      });
      setIsChromeCollapsed(false);
      requestAnimationFrame(() => {
        // A pending approval or checkpoint is the reason most collapse ->
        // expand transitions happen at all, but the interaction that
        // triggered it didn't exist yet when `expandedSize` was captured at
        // collapse time. Restoring only that stale pre-collapse frame is
        // exactly the "opens, but not to the right size" bug: measure the
        // now-visible overlay (uncollapsing above already un-hides
        // `.widget-body`, so its content has laid out by this rAF) and grow
        // to fit it in this same resize request, rather than restoring the
        // old frame and hoping a later measurement pass corrects it.
        const interactiveTarget = measureInteractiveOverlayTarget();
        let currentWidth = expandedSize.width;
        let currentHeight = expandedSize.height;
        if (interactiveTarget) {
          const header = document.querySelector('.widget-header') as HTMLElement | null;
          const headerH = header?.offsetHeight ?? 52;
          const rootPadding = WEBKIT_WINDOW_CHROME_FRAME_INSET_PX * 2;
          const minH = 180;
          const maxH = 700;
          const interactiveWidth = Math.max(interactiveTarget.width + sidebarWidth, layoutMinimumWidth);
          const interactiveHeight = Math.min(
            Math.max(headerH + interactiveTarget.height + rootPadding, minH),
            maxH,
          );
          currentWidth = Math.max(currentWidth, interactiveWidth);
          currentHeight = Math.max(currentHeight, interactiveHeight);
        }
        logResizeTrace('collapse expanding request', {
          currentWidth,
          restoredHeight: expandedSize.height,
          resolvedHeight: currentHeight,
          interactiveTarget,
          windowHeightAtRequest: window.innerHeight,
          lastRequestedSizeBeforeRequest: lastRequestedSize.current,
        });
        lastRequestedSize.current = { width: currentWidth, height: currentHeight };
        requestResize(currentWidth, currentHeight, 'expanded', layoutMinimumWidth);
        expandedSizeBeforeCollapseRef.current = null;
      });
    } else {
      setIsChromeCollapsed(false);
    }
  }, [layoutMinimumWidth, sidebarWidth]);

  const handleToggleChromeCollapsed = useCallback(() => {
    if (isChromeCollapsed) {
      expandChrome();
    } else {
      collapseChrome();
    }
  }, [collapseChrome, expandChrome, isChromeCollapsed]);

  const needsUserInput =
    selectedAgent?.showApprovalPrompt === true ||
    selectedAgent?.showCheckpointPrompt === true ||
    selectedAgent?.status === 'awaitingInput';

  useEffect(() => {
    const needsInputStarted = needsUserInput && !prevNeedsInputRef.current;
    prevNeedsInputRef.current = needsUserInput;
    if (needsInputStarted && isChromeCollapsed) {
      expandChrome();
    }
  }, [expandChrome, isChromeCollapsed, needsUserInput]);

  return {
    rootRef,
    sidebarWidth,
    detailTrayWidth,
    detailTrayOpen,
    detailTrayMode,
    setDetailTrayOpen,
    openDetailTray,
    setDetailTrayMode,
    setDetailTrayWidth,
    isChromeCollapsed,
    isCollapseIconRotated,
    handleToggleChromeCollapsed,
    expandChrome,
    setTrayResizing,
  };
}

