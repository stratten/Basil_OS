import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';

export const TODO_WORKSPACE_PANE_DEFAULT_WIDTH = 360;
export const TODO_WORKSPACE_PANE_MIN_WIDTH = 300;
export const TODO_WORKSPACE_PANE_KEYBOARD_STEP = 24;

const RESIZE_ACTIVATION_DISTANCE_PX = 4;

interface ResizeSession {
  pointerId: number;
  startX: number;
  startWidth: number;
  isActive: boolean;
}

function maximumPaneWidth(): number {
  return Math.max(TODO_WORKSPACE_PANE_MIN_WIDTH, Math.floor(window.innerWidth * 0.55));
}

function clampPaneWidth(width: number, maxWidth: number): number {
  return Math.min(Math.max(Math.round(width), TODO_WORKSPACE_PANE_MIN_WIDTH), maxWidth);
}

/**
 * Drag-to-resize behavior for the To-Do workspace pane, mirroring
 * `useConversationArtifactSidebarResize` (chats artifact sidebar) and the
 * Agent Task result tray's own resize handle so all three right-hand panes
 * behave the same way.
 */
export function useTodoWorkspacePaneResize() {
  const [maximumWidth, setMaximumWidth] = useState(maximumPaneWidth);
  const [width, setWidth] = useState(() => clampPaneWidth(TODO_WORKSPACE_PANE_DEFAULT_WIDTH, maximumPaneWidth()));
  const [isResizing, setIsResizing] = useState(false);
  const resizeSession = useRef<ResizeSession>();

  useEffect(() => {
    const updateMaximumWidth = () => {
      const nextMaximumWidth = maximumPaneWidth();
      setMaximumWidth(nextMaximumWidth);
      setWidth((current) => clampPaneWidth(current, nextMaximumWidth));
    };
    window.addEventListener('resize', updateMaximumWidth);
    return () => window.removeEventListener('resize', updateMaximumWidth);
  }, []);

  const resize = useCallback((nextWidth: number) => {
    setWidth(clampPaneWidth(nextWidth, maximumWidth));
  }, [maximumWidth]);

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    resizeSession.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: width,
      isActive: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }, [width]);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const session = resizeSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    // The handle sits on the pane's left edge, so dragging left (negative
    // horizontal distance) grows the pane.
    const horizontalDistance = event.clientX - session.startX;
    if (!session.isActive) {
      if (Math.abs(horizontalDistance) < RESIZE_ACTIVATION_DISTANCE_PX) return;
      session.isActive = true;
      setIsResizing(true);
    }
    event.preventDefault();
    resize(session.startWidth - horizontalDistance);
  }, [resize]);

  const finishResize = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const session = resizeSession.current;
    if (!session || session.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    resizeSession.current = undefined;
    if (session.isActive) setIsResizing(false);
  }, []);

  const handleKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      resize(width + TODO_WORKSPACE_PANE_KEYBOARD_STEP);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      resize(width - TODO_WORKSPACE_PANE_KEYBOARD_STEP);
    } else if (event.key === 'Home') {
      event.preventDefault();
      resize(TODO_WORKSPACE_PANE_MIN_WIDTH);
    } else if (event.key === 'End') {
      event.preventDefault();
      resize(maximumWidth);
    }
  }, [maximumWidth, resize, width]);

  return {
    isResizing,
    maximumWidth,
    resizeHandleProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: finishResize,
      onPointerCancel: finishResize,
      onLostPointerCapture: finishResize,
      onKeyDown: handleKeyDown,
    },
    paneStyle: { '--todo-workspace-pane-width': `${width}px` } as CSSProperties,
    width,
  };
}
