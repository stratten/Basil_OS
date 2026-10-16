import { Children, useId, useLayoutEffect, useState, type CSSProperties, type ReactNode } from 'react';
import { useExpandableHeight } from './useExpandableHeight';

const DEFAULT_COLLAPSED_COUNT = 5;
// Items that wrap onto the same visual row can differ by a fraction of a pixel in their top edge.
const ROW_TOP_TOLERANCE_PX = 4;

export interface ExpandableListProps {
  /** Each child must render exactly one root element, because the collapsed height is measured from the content's element children. */
  children: ReactNode;
  /** Number of items shown while collapsed. Ignored when `collapsedRows` is set. Defaults to 5. */
  collapsedCount?: number;
  /** Visual rows shown while collapsed, for wrapping layouts such as tab strips. */
  collapsedRows?: number;
  /** Controlled expansion. Leave undefined for the list to manage its own state. */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  /** Index of an item that must stay inside the collapsed window, such as the active tab. */
  keepVisibleIndex?: number;
  /** Toggle text while collapsed; receives the total item count. */
  showAllLabel?: (total: number) => string;
  showFewerLabel?: string;
  className?: string;
  contentClassName?: string;
  contentRole?: string;
  contentAriaLabel?: string;
  toggleClassName?: string;
}

function collapsedBottom(content: HTMLElement, collapsedCount: number | undefined, collapsedRows: number | undefined): number {
  const items = Array.from(content.children);
  if (items.length === 0) return 0;
  const contentTop = content.getBoundingClientRect().top;
  if (collapsedRows === undefined) {
    const visibleCount = Math.max(1, Math.min(collapsedCount ?? DEFAULT_COLLAPSED_COUNT, items.length));
    return items[visibleCount - 1].getBoundingClientRect().bottom - contentTop;
  }
  let rowCount = 0;
  let rowTop = Number.NEGATIVE_INFINITY;
  let bottom = 0;
  for (const item of items) {
    const rect = item.getBoundingClientRect();
    if (rect.top - rowTop > ROW_TOP_TOLERANCE_PX) {
      rowCount += 1;
      rowTop = rect.top;
    }
    if (rowCount > Math.max(1, collapsedRows)) break;
    bottom = Math.max(bottom, rect.bottom - contentTop);
  }
  return bottom;
}

/** Whether any item sits beyond the collapsed window. Compares item positions, not pixel heights, so item margins and line boxes cannot report hidden items that do not exist. */
function hasItemsBeyondCollapsed(content: HTMLElement, collapsedCount: number | undefined, collapsedRows: number | undefined): boolean {
  const items = Array.from(content.children);
  if (collapsedRows === undefined) return items.length > (collapsedCount ?? DEFAULT_COLLAPSED_COUNT);
  let rowCount = 0;
  let rowTop = Number.NEGATIVE_INFINITY;
  for (const item of items) {
    const top = item.getBoundingClientRect().top;
    if (top - rowTop > ROW_TOP_TOLERANCE_PX) {
      rowCount += 1;
      rowTop = top;
    }
    if (rowCount > Math.max(1, collapsedRows)) return true;
  }
  return false;
}

/**
 * A list that shows its first items and animates open to show the rest, on the same height animation as `ExpandableClamp`. Items past the collapsed window are `inert`, so they cannot be focused or read while hidden.
 */
export default function ExpandableList({
  children,
  collapsedCount,
  collapsedRows,
  expanded: controlledExpanded,
  onExpandedChange,
  keepVisibleIndex,
  showAllLabel = total => `Show all ${total}`,
  showFewerLabel = 'Show fewer',
  className,
  contentClassName,
  contentRole,
  contentAriaLabel,
  toggleClassName,
}: ExpandableListProps) {
  const items = Children.toArray(children);
  const total = items.length;
  const contentId = useId();
  const [internalExpanded, setInternalExpanded] = useState(false);
  const expanded = controlledExpanded ?? internalExpanded;
  const effectiveCollapsedCount = collapsedRows === undefined ? collapsedCount ?? DEFAULT_COLLAPSED_COUNT : undefined;
  const { frameRef, contentRef, collapsed, collapsedHeight, overflows, handleTransitionEnd } = useExpandableHeight({
    expanded,
    measureCollapsedHeight: content => collapsedBottom(content, effectiveCollapsedCount, collapsedRows),
    trackCollapsedHeight: true,
    detectOverflow: content => hasItemsBeyondCollapsed(content, effectiveCollapsedCount, collapsedRows),
    contentKey: `${total}:${effectiveCollapsedCount ?? ''}:${collapsedRows ?? ''}`,
  });

  const hasHiddenItems = effectiveCollapsedCount === undefined ? overflows : total > effectiveCollapsedCount;
  const showingCollapsed = hasHiddenItems && collapsed;

  useLayoutEffect(() => {
    const frame = frameRef.current;
    const content = contentRef.current;
    if (!frame || !content) return;
    const elements = Array.from(content.children);
    if (!showingCollapsed || collapsedHeight === undefined) {
      frame.scrollTop = 0;
      elements.forEach(element => element.removeAttribute('inert'));
      return;
    }
    const contentTop = content.getBoundingClientRect().top;
    const keepVisible = keepVisibleIndex === undefined ? undefined : elements[keepVisibleIndex];
    const keepVisibleBottom = keepVisible ? keepVisible.getBoundingClientRect().bottom - contentTop : 0;
    const scrollTop = Math.max(0, Math.ceil(keepVisibleBottom - collapsedHeight));
    frame.scrollTop = scrollTop;
    elements.forEach(element => {
      const rect = element.getBoundingClientRect();
      const hidden = rect.top - contentTop >= scrollTop + collapsedHeight - 1 || rect.bottom - contentTop <= scrollTop + 1;
      element.toggleAttribute('inert', hidden);
    });
  }, [collapsedHeight, contentRef, frameRef, keepVisibleIndex, showingCollapsed, total]);

  const toggle = () => {
    const next = !expanded;
    if (controlledExpanded === undefined) setInternalExpanded(next);
    onExpandedChange?.(next);
  };

  const frameClassName = ['basil-expandable-list__frame', showingCollapsed ? 'is-collapsed' : ''].filter(Boolean).join(' ');
  const frameStyle = (
    collapsedHeight === undefined ? undefined : { '--basil-expandable-list-collapsed-height': `${collapsedHeight}px` }
  ) as CSSProperties | undefined;

  return (
    <div className={['basil-expandable-list', className].filter(Boolean).join(' ')}>
      <div ref={frameRef} className={frameClassName} style={frameStyle} onTransitionEnd={handleTransitionEnd}>
        <div
          ref={contentRef}
          id={contentId}
          className={['basil-expandable-list__content', contentClassName].filter(Boolean).join(' ')}
          role={contentRole}
          aria-label={contentAriaLabel}
        >
          {items}
        </div>
      </div>
      {hasHiddenItems && (
        <button
          type="button"
          className={['basil-expandable-list__toggle', toggleClassName].filter(Boolean).join(' ')}
          aria-expanded={expanded}
          aria-controls={contentId}
          onClick={toggle}
        >
          {expanded ? showFewerLabel : showAllLabel(total)}
        </button>
      )}
    </div>
  );
}
