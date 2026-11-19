import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type TransitionEvent } from 'react';
import { settleWhenUntransitioned } from './presenceTransitionSettle';

interface CrossfadeStackProps {
  contentKey: string;
  className: string;
  children: ReactNode;
  as?: 'div' | 'main';
  layerClassName?: string;
  settleWithoutTransition?: boolean;
  onOutgoingTransitionComplete?: () => void;
}

export default function CrossfadeStack({
  contentKey,
  className,
  children,
  as: Root = 'div',
  layerClassName,
  settleWithoutTransition = false,
  onOutgoingTransitionComplete,
}: CrossfadeStackProps) {
  const previous = useRef({ key: contentKey, children });
  const outgoingLayerRef = useRef<HTMLDivElement>(null);
  const [outgoing, setOutgoing] = useState<{ key: string; children: ReactNode } | null>(null);
  const [entering, setEntering] = useState(false);
  const enteringFrameRef = useRef<number>();
  const resolvedLayerClassName = layerClassName ?? `${className}-layer`;

  useLayoutEffect(() => {
    if (previous.current.key === contentKey) {
      previous.current = { key: contentKey, children };
      return;
    }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      previous.current = { key: contentKey, children };
      setOutgoing(null);
      setEntering(false);
      onOutgoingTransitionComplete?.();
      return;
    }
    setOutgoing(previous.current);
    previous.current = { key: contentKey, children };
    setEntering(true);
    // This effect also re-runs whenever the parent hands over new children, so the frame must not be canceled by its cleanup: a re-render before the next frame would leave the layer entering (invisible) for good.
    if (enteringFrameRef.current !== undefined) cancelAnimationFrame(enteringFrameRef.current);
    enteringFrameRef.current = requestAnimationFrame(() => {
      enteringFrameRef.current = undefined;
      setEntering(false);
    });
  }, [children, contentKey, onOutgoingTransitionComplete]);

  useEffect(() => () => {
    if (enteringFrameRef.current !== undefined) cancelAnimationFrame(enteringFrameRef.current);
  }, []);

  const finishOutgoing = useCallback(() => {
    setOutgoing(null);
    onOutgoingTransitionComplete?.();
  }, [onOutgoingTransitionComplete]);

  useLayoutEffect(() => {
    if (!settleWithoutTransition || !outgoing || !outgoingLayerRef.current) return;
    return settleWhenUntransitioned(outgoingLayerRef.current, finishOutgoing);
  }, [finishOutgoing, outgoing, settleWithoutTransition]);

  const completeOutgoing = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== 'opacity') return;
    finishOutgoing();
  };

  return (
    <Root className={className}>
      {outgoing && (
        <div
          key={outgoing.key}
          ref={outgoingLayerRef}
          className={resolvedLayerClassName}
          data-presence-phase="exiting"
          aria-hidden="true"
          {...{ inert: '' }}
          onTransitionEnd={completeOutgoing}
        >
          {outgoing.children}
        </div>
      )}
      <div
        key={contentKey}
        className={resolvedLayerClassName}
        data-presence-phase={entering ? 'entering' : 'present'}
      >
        {children}
      </div>
    </Root>
  );
}
