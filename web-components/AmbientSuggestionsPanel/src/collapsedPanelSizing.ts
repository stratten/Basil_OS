export const AMBIENT_COMPACT_MAX_WIDTH = 400;
export const AMBIENT_COMPACT_MIN_WIDTH = 220;

export interface CollapsedPanelSize {
  width: number;
  height: number;
}

export function resolveCollapsedPanelSize(
  intrinsicHeaderWidth: number,
  headerHeight: number,
): CollapsedPanelSize {
  return {
    width: Math.min(
      AMBIENT_COMPACT_MAX_WIDTH,
      Math.max(AMBIENT_COMPACT_MIN_WIDTH, Math.ceil(intrinsicHeaderWidth)),
    ),
    height: Math.max(64, Math.ceil(headerHeight)),
  };
}

export function measureCollapsedPanelSize(
  header: HTMLElement | null,
): CollapsedPanelSize {
  if (!header) {
    return {
      width: AMBIENT_COMPACT_MIN_WIDTH,
      height: 64,
    };
  }
  const headerLeft = header.querySelector<HTMLElement>('[data-ambient-header-left]');
  const styles = getComputedStyle(header);
  const padding = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
  return resolveCollapsedPanelSize(
    (headerLeft?.scrollWidth ?? 0) + (Number.isFinite(padding) ? padding : 0),
    header.offsetHeight,
  );
}
