import { useRef, type ReactNode } from 'react';
import { usePresenceTransition } from '../app/usePresenceTransition';

interface PresenceRegionProps {
  visible: boolean;
  className: string;
  children: ReactNode;
}

export default function PresenceRegion({ visible, className, children }: PresenceRegionProps) {
  const presence = usePresenceTransition(visible);
  const retainedChildren = useRef(children);
  if (visible) retainedChildren.current = children;
  if (!presence.shouldRender) return null;

  return (
    <div
      className={className}
      data-presence-phase={presence.phase}
      aria-hidden={presence.phase === 'exiting' ? true : undefined}
      inert={presence.phase === 'exiting' ? '' : undefined}
      onTransitionEnd={presence.completeTransition}
    >
      {retainedChildren.current}
    </div>
  );
}
