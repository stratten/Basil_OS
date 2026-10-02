import type { ReactNode } from 'react';

interface CollapsibleSidebarProps {
  expanded: boolean;
  className?: string;
  ariaLabel?: string;
  element?: 'aside' | 'div';
  collapsedContent: ReactNode;
  children: ReactNode;
}

// Both layers stay mounted so the width transition and crossfade run in both directions; the inactive layer is inert and hidden from assistive technology.
export default function CollapsibleSidebar({
  expanded,
  className,
  ariaLabel,
  element = 'aside',
  collapsedContent,
  children,
}: CollapsibleSidebarProps) {
  const Root = element;
  const rootClassName = ['basil-collapsible-sidebar', expanded ? 'is-expanded' : 'is-collapsed', className].filter(Boolean).join(' ');
  return (
    <Root className={rootClassName} aria-label={ariaLabel}>
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
