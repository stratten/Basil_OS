import { useLayoutEffect, useRef, useState, type ReactNode, type TransitionEvent } from 'react';

interface CrossfadeStackProps {
  contentKey: string;
  className: string;
  children: ReactNode;
  as?: 'div' | 'main';
  onOutgoingTransitionComplete?: () => void;
}

export default function CrossfadeStack({
  contentKey,
  className,
  children,
  as: Root = 'div',
  onOutgoingTransitionComplete,
}: CrossfadeStackProps) {
  const previous = useRef({ key: contentKey, children });
  const [outgoing, setOutgoing] = useState<{ key: string; children: ReactNode } | null>(null);
  const [entering, setEntering] = useState(false);

  useLayoutEffect(() => {
    if (previous.current.key === contentKey) {
      previous.current = { key: contentKey, children };
      return;
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      previous.current = { key: contentKey, children };
      setOutgoing(null);
      onOutgoingTransitionComplete?.();
      return;
    }
    setOutgoing(previous.current);
    previous.current = { key: contentKey, children };
    setEntering(true);
    const frame = requestAnimationFrame(() => setEntering(false));
    return () => cancelAnimationFrame(frame);
  }, [children, contentKey, onOutgoingTransitionComplete]);

  const completeOutgoing = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== 'opacity') return;
    setOutgoing(null);
    onOutgoingTransitionComplete?.();
  };

  return (
    <Root className={className}>
      {outgoing && (
        <div
          className={`${className}-layer`}
          data-presence-phase="exiting"
          aria-hidden="true"
          inert=""
          onTransitionEnd={completeOutgoing}
        >
          {outgoing.children}
        </div>
      )}
      <div
        className={`${className}-layer`}
        data-presence-phase={entering ? 'entering' : 'present'}
      >
        {children}
      </div>
    </Root>
  );
}
