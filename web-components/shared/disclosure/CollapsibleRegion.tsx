import type { ReactNode } from 'react';
import { useExpandableHeight } from './useExpandableHeight';

interface CollapsibleRegionProps {
  expanded: boolean;
  className?: string;
  id?: string;
  children: ReactNode;
}

/**
 * A region that animates between its full height and nothing, for an in-page section the reader opens and closes (a settings section, a pinned strip). It is the zero-height case of `useExpandableHeight`, the same height animation `ExpandableClamp` and `ExpandableList` use; the duration and easing live in `collapsible-region.css`. Collapsed content is inert so keyboard focus and assistive technology skip it, and it stays mounted so a draft or scroll position inside it survives.
 *
 * Use `useSettledExpand` instead only for collapsing a whole host window, which has to wait for the native window resize.
 */
export default function CollapsibleRegion({ expanded, className, id, children }: CollapsibleRegionProps) {
  const { frameRef, contentRef, collapsed, handleTransitionEnd } = useExpandableHeight({
    expanded,
    measureCollapsedHeight: () => 0,
  });

  const frameClassName = ['basil-collapsible-region', collapsed ? 'is-collapsed' : '', className].filter(Boolean).join(' ');
  const hidden = !expanded;

  return (
    <div
      ref={frameRef}
      id={id}
      className={frameClassName}
      onTransitionEnd={handleTransitionEnd}
      aria-hidden={hidden ? true : undefined}
      {...(hidden ? { inert: '' } : {})}
    >
      <div ref={contentRef} className="basil-collapsible-region__content">
        {children}
      </div>
    </div>
  );
}
