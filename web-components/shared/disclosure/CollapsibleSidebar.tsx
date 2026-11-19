import type { CSSProperties, ReactNode } from 'react';

interface CollapsibleSidebarProps {
  expanded: boolean;
  className?: string;
  /** Per-instance values for the sidebar's width custom properties. */
  style?: CSSProperties;
  ariaLabel?: string;
  element?: 'aside' | 'div';
  /** Which window edge the sidebar sits on; an `end` sidebar anchors its layers to the right so the width transition reveals it from the right edge. */
  side?: 'start' | 'end';
  collapsedContent: ReactNode;
  children: ReactNode;
}

// Both layers stay mounted so the width transition and crossfade run in both directions; the inactive layer is inert and hidden from assistive technology.
export default function CollapsibleSidebar({
  expanded,
  className,
  style,
  ariaLabel,
  element = 'aside',
  side = 'start',
  collapsedContent,
  children,
}: CollapsibleSidebarProps) {
  const Root = element;
  const rootClassName = ['basil-collapsible-sidebar', side === 'end' ? 'basil-collapsible-sidebar--end' : '', expanded ? 'is-expanded' : 'is-collapsed', className].filter(Boolean).join(' ');
  return (
    <Root className={rootClassName} style={style} aria-label={ariaLabel}>
      <div
        className="basil-collapsible-sidebar__layer basil-collapsible-sidebar__layer--collapsed"
        aria-hidden={expanded}
        {...(expanded ? { inert: '' } : {})}
      >
        {collapsedContent}
      </div>
      <div
        className="basil-collapsible-sidebar__layer basil-collapsible-sidebar__layer--expanded"
        aria-hidden={!expanded}
        {...(expanded ? {} : { inert: '' })}
      >
        {children}
      </div>
    </Root>
  );
}
