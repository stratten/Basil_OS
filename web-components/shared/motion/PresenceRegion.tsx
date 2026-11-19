import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { usePresenceTransition } from './usePresenceTransition';
import { settleWhenUntransitioned } from './presenceTransitionSettle';

interface PresenceRegionProps {
  visible: boolean;
  className: string;
  children: ReactNode;
  role?: string;
  settleWithoutTransition?: boolean;
}

export default function PresenceRegion({ visible, className, children, role, settleWithoutTransition = false }: PresenceRegionProps) {
  const presence = usePresenceTransition(visible);
  const { phase, settle } = presence;
  const elementRef = useRef<HTMLDivElement>(null);
  const retainedChildren = useRef(children);
  if (visible) retainedChildren.current = children;

  useLayoutEffect(() => {
    if (!settleWithoutTransition || phase !== 'exiting' || !elementRef.current) return;
    return settleWhenUntransitioned(elementRef.current, settle);
  }, [phase, settle, settleWithoutTransition]);

  if (!presence.shouldRender) return null;

  return (
    <div
      ref={elementRef}
      className={className}
      role={role}
      data-presence-phase={phase}
      aria-hidden={phase === 'exiting' ? true : undefined}
      {...(phase === 'exiting' ? { inert: '' } : {})}
      onTransitionEnd={presence.completeTransition}
    >
      {retainedChildren.current}
    </div>
  );
}
