import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type TransitionEvent } from 'react';
import { settleWhenUntransitioned } from './presenceTransitionSettle';

interface ExpandableClampProps {
  expanded: boolean;
  /** Lines of text visible while collapsed. */
  collapsedLines?: number;
  className?: string;
  children: ReactNode;
}

// Collapsed content is line-clamped, which cannot be transitioned, so the frame's explicit pixel height is what animates. The clamp is lifted at the start of an expand and restored only once a collapse has finished, so the text is never cut off mid-animation. The duration and easing live in `expandable-clamp.css` and match the collapsible sidebar's motion.
export default function ExpandableClamp({ expanded, collapsedLines = 3, className, children }: ExpandableClampProps) {
  const frameRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const previousExpanded = useRef(expanded);
  const finishRef = useRef<(() => void) | null>(null);
  const [clamped, setClamped] = useState(!expanded);

  useLayoutEffect(() => {
    if (previousExpanded.current === expanded) return undefined;
    previousExpanded.current = expanded;
    const frame = frameRef.current;
    const content = contentRef.current;
    if (!frame || !content) {
      setClamped(!expanded);
      return undefined;
    }

    // Measured from the live frame so a toggle during a running animation continues from where it currently is.
    const startHeight = frame.offsetHeight;
    // A clamped element still reports its full content height as scrollHeight.
    const fullHeight = content.scrollHeight;
    const lineHeight = Number.parseFloat(window.getComputedStyle(content).lineHeight);
    const clampedHeight = Number.isFinite(lineHeight) ? Math.min(fullHeight, Math.ceil(lineHeight * collapsedLines)) : fullHeight;
    const targetHeight = expanded ? fullHeight : clampedHeight;

    const finish = () => {
      finishRef.current = null;
      frame.style.height = '';
      if (!expanded) setClamped(true);
    };
    finishRef.current = finish;

    if (expanded) setClamped(false);
    frame.style.height = `${startHeight}px`;
    // Reading layout commits the starting height so the next assignment transitions instead of jumping.
    void frame.offsetHeight;
    frame.style.height = `${targetHeight}px`;

    // transitionend never fires when there is no transition (reduced motion, or no height change), so settle those cases directly.
    const cancelSettle = settleWhenUntransitioned(frame, () => finishRef.current?.());
    return () => {
      cancelSettle();
      finishRef.current = null;
    };
  }, [collapsedLines, expanded]);

  const handleTransitionEnd = (event: TransitionEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || event.propertyName !== 'height') return;
    finishRef.current?.();
  };

  const frameClassName = ['basil-expandable-clamp', className].filter(Boolean).join(' ');
  const contentClassName = ['basil-expandable-clamp__content', clamped ? 'is-clamped' : ''].filter(Boolean).join(' ');
  const style = { '--basil-expandable-clamp-lines': collapsedLines } as CSSProperties;

  return (
    <div ref={frameRef} className={frameClassName} style={style} onTransitionEnd={handleTransitionEnd}>
      <div ref={contentRef} className={contentClassName}>
        {children}
      </div>
    </div>
  );
}
