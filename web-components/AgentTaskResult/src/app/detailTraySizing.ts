export type DetailTrayMode = 'overview' | 'detail' | 'preview';

export const DETAIL_TRAY_OVERVIEW_WIDTH = 280;
export const DETAIL_TRAY_DETAIL_WIDTH = 320;
export const DETAIL_TRAY_PREVIEW_WIDTH = 400;
export const DETAIL_TRAY_MIN_WIDTH = DETAIL_TRAY_OVERVIEW_WIDTH;
export const DETAIL_TRAY_KEYBOARD_STEP = 16;
export const COLLAPSED_RUN_RAIL_WIDTH = 44;
export const STANDALONE_COLLAPSED_DEFAULT_WIDTH = 444;
export const STANDALONE_COLLAPSED_MINIMUM_WIDTH = 444;
export const STANDALONE_SIDEBAR_EXPANSION_WIDTH = 192;

export function detailTrayPreferredWidth(mode: DetailTrayMode): number {
  if (mode === 'overview') return DETAIL_TRAY_OVERVIEW_WIDTH;
  if (mode === 'preview') return DETAIL_TRAY_PREVIEW_WIDTH;
  return DETAIL_TRAY_DETAIL_WIDTH;
}

export function clampDetailTrayWidth(width: number): number {
  if (!Number.isFinite(width)) return DETAIL_TRAY_DETAIL_WIDTH;
  return Math.max(DETAIL_TRAY_MIN_WIDTH, Math.round(width));
}

export function standaloneMinimumWidth(sidebarExpanded: boolean, detailTrayWidth?: number): number {
  const rightAccessoryWidth = detailTrayWidth ?? COLLAPSED_RUN_RAIL_WIDTH;
  return 400 + (sidebarExpanded ? STANDALONE_SIDEBAR_EXPANSION_WIDTH : 0) + rightAccessoryWidth;
}

export function standaloneDefaultWidth(_sidebarExpanded: boolean): number {
  return STANDALONE_COLLAPSED_DEFAULT_WIDTH;
}
