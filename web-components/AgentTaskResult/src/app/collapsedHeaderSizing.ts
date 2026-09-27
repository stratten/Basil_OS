// The collapsed agent-task widget is a single fixed size. Measuring the header
// content (title/subject width) previously let the collapsed width drift between
// tasks, which read as the strip "shifting" whenever a new status arrived. A
// fixed width removes that drift and trims the wasted horizontal space; the
// header's title/subject already truncate with an ellipsis to fit.
export const AGENT_TASK_COMPACT_WIDTH = 300;
// The collapsed identity column (window title + task title + status) lives
// inside .basil-webkit-window-frame's 4px inset on every side, so the actual
// content box the header lays out into is 8px shorter than this value. At
// 74px that box (66px) left the task title and the bottom-anchored status
// with no spare vertical room between them, which read as the status
// crowding/overlapping the task title above it. +4px here grows only the
// bottom-anchored status's clearance (the title/subject stay pinned to the
// top and are unaffected), moving the status down and widening that gap by
// the same 4px, with no risk of clipping since it's added room rather than
// reclaimed room. Swift derives the native window's size entirely from the
// width/height this module reports (see requestResize in
// useResultWidgetSizing.ts and compactSize(_:visibleFrame:) in
// WindowChromeCollapse.swift, which takes the size as a parameter rather
// than hardcoding one), so this is the single place that needs updating.
export const AGENT_TASK_COMPACT_HEIGHT = 78;

export interface CollapsedHeaderSize {
  width: number;
  height: number;
}

// The `header` argument is retained so the sizing hook's call site is unchanged,
// but the collapsed size is fixed and no longer derived from the DOM.
export function measureCollapsedHeaderSize(
  _header?: HTMLElement | null,
): CollapsedHeaderSize {
  return { width: AGENT_TASK_COMPACT_WIDTH, height: AGENT_TASK_COMPACT_HEIGHT };
}
