import { useCallback, useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';

export const CONVERSATION_ARTIFACT_SIDEBAR_DEFAULT_WIDTH = 420;
export const CONVERSATION_ARTIFACT_SIDEBAR_MIN_WIDTH = 320;
export const CONVERSATION_ARTIFACT_SIDEBAR_KEYBOARD_STEP = 24;

const RESIZE_ACTIVATION_DISTANCE_PX = 4;

interface ResizeSession {
  pointerId: number;
  startX: number;
  startWidth: number;
  isActive: boolean;
}

function maximumSidebarWidth(): number {
  return Math.max(CONVERSATION_ARTIFACT_SIDEBAR_MIN_WIDTH, Math.floor(window.innerWidth * 0.55));
}

function clampSidebarWidth(width: number, maxWidth: number): number {
  return Math.min(Math.max(Math.round(width), CONVERSATION_ARTIFACT_SIDEBAR_MIN_WIDTH), maxWidth);
}

export function useConversationArtifactSidebarResize() {
  const [maximumWidth, setMaximumWidth] = useState(maximumSidebarWidth);
  const [width, setWidth] = useState(() => clampSidebarWidth(CONVERSATION_ARTIFACT_SIDEBAR_DEFAULT_WIDTH, maximumSidebarWidth()));
  const [isResizing, setIsResizing] = useState(false);
  const resizeSession = useRef<ResizeSession>();

  useEffect(() => {
    const updateMaximumWidth = () => {
      const nextMaximumWidth = maximumSidebarWidth();
      setMaximumWidth(nextMaximumWidth);
      setWidth((current) => clampSidebarWidth(current, nextMaximumWidth));
    };
    window.addEventListener('resize', updateMaximumWidth);
    return () => window.removeEventListener('resize', updateMaximumWidth);
  }, []);

  const resize = useCallback((nextWidth: number) => {
    setWidth(clampSidebarWidth(nextWidth, maximumWidth));
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
      resize(width + CONVERSATION_ARTIFACT_SIDEBAR_KEYBOARD_STEP);
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      resize(width - CONVERSATION_ARTIFACT_SIDEBAR_KEYBOARD_STEP);
    } else if (event.key === 'Home') {
      event.preventDefault();
      resize(CONVERSATION_ARTIFACT_SIDEBAR_MIN_WIDTH);
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
    sidebarStyle: { '--chats-artifact-sidebar-width': `${width}px` } as CSSProperties,
    width,
  };
}
