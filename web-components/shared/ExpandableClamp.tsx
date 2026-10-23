import type { CSSProperties, ReactNode } from 'react';
import { useExpandableHeight } from './useExpandableHeight';

interface ExpandableClampProps {
  expanded: boolean;
  /** Lines of text visible while collapsed. */
  collapsedLines?: number;
  className?: string;
  children: ReactNode;
}

// Collapsed content is line-clamped, which cannot be transitioned, so the frame's explicit pixel height is what animates (see `useExpandableHeight`). The clamp is lifted at the start of an expand and restored only once a collapse has finished, so the text is never cut off mid-animation. The duration and easing live in `expandable-clamp.css` and match the collapsible sidebar's motion.
export default function ExpandableClamp({ expanded, collapsedLines = 3, className, children }: ExpandableClampProps) {
  const { frameRef, contentRef, collapsed, handleTransitionEnd } = useExpandableHeight({
    expanded,
    measureCollapsedHeight: content => Number.parseFloat(window.getComputedStyle(content).lineHeight) * collapsedLines,
  });

  const frameClassName = ['basil-expandable-clamp', className].filter(Boolean).join(' ');
  const contentClassName = ['basil-expandable-clamp__content', collapsed ? 'is-clamped' : ''].filter(Boolean).join(' ');
  const style = { '--basil-expandable-clamp-lines': collapsedLines } as CSSProperties;

  return (
    <div ref={frameRef} className={frameClassName} style={style} onTransitionEnd={handleTransitionEnd}>
      <div ref={contentRef} className={contentClassName}>
        {children}
      </div>
    </div>
  );
}
