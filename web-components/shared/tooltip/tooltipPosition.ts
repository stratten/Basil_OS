export type TooltipPlacement = 'above' | 'below' | 'left' | 'right';

export interface TooltipAnchorBox {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface TooltipSize {
  width: number;
  height: number;
}

export interface TooltipPosition {
  top: number;
  left: number;
  placement: TooltipPlacement;
}

export const TOOLTIP_GAP_PX = 6;
export const TOOLTIP_VIEWPORT_MARGIN_PX = 10;

const PLACEMENT_FALLBACKS: Readonly<Record<TooltipPlacement, readonly TooltipPlacement[]>> = {
  below: ['below', 'above'],
  above: ['above', 'below'],
  left: ['left', 'right', 'below', 'above'],
  right: ['right', 'left', 'below', 'above'],
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), Math.max(min, max));
}

function placementOrigin(anchor: TooltipAnchorBox, size: TooltipSize, placement: TooltipPlacement): { top: number; left: number } {
  const centeredLeft = anchor.left + anchor.width / 2 - size.width / 2;
  const centeredTop = anchor.top + anchor.height / 2 - size.height / 2;
  switch (placement) {
    case 'below':
      return { top: anchor.top + anchor.height + TOOLTIP_GAP_PX, left: centeredLeft };
    case 'above':
      return { top: anchor.top - TOOLTIP_GAP_PX - size.height, left: centeredLeft };
    case 'left':
      return { top: centeredTop, left: anchor.left - TOOLTIP_GAP_PX - size.width };
    case 'right':
      return { top: centeredTop, left: anchor.left + anchor.width + TOOLTIP_GAP_PX };
  }
}

function fitsMainAxis(placement: TooltipPlacement, origin: { top: number; left: number }, size: TooltipSize, viewport: TooltipSize): boolean {
  const margin = TOOLTIP_VIEWPORT_MARGIN_PX;
  if (placement === 'below' || placement === 'above') {
    return origin.top >= margin && origin.top + size.height <= viewport.height - margin;
  }
  return origin.left >= margin && origin.left + size.width <= viewport.width - margin;
}

export function computeTooltipPosition(
  anchor: TooltipAnchorBox,
  size: TooltipSize,
  viewport: TooltipSize,
  preferred: TooltipPlacement = 'below',
): TooltipPosition {
  const fallbacks = PLACEMENT_FALLBACKS[preferred];
  let placement = preferred;
  let origin = placementOrigin(anchor, size, preferred);
  for (const candidate of fallbacks) {
    const candidateOrigin = placementOrigin(anchor, size, candidate);
    if (fitsMainAxis(candidate, candidateOrigin, size, viewport)) {
      placement = candidate;
      origin = candidateOrigin;
      break;
    }
  }
  const margin = TOOLTIP_VIEWPORT_MARGIN_PX;
  return {
    placement,
    top: Math.round(clamp(origin.top, margin, viewport.height - margin - size.height)),
    left: Math.round(clamp(origin.left, margin, viewport.width - margin - size.width)),
  };
}
