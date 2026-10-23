import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { InitMessage, MeetingInfo } from './types';
import {
  dismissMeeting,
  notifyReady,
  registerInitHandler,
  registerMeetingHandler,
  registerThemeHandler,
  requestResize,
  startMeeting,
} from './services/bridge';
import { applyHostTheme } from './app/themeBootstrap';

const PANEL_WIDTH = 340;
const SYSTEM_FONT_FALLBACK = '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif';

function toCssFontFamily(rawName: string | null | undefined): string {
  const trimmed = (rawName ?? '').trim();
  if (!trimmed) {
    return SYSTEM_FONT_FALLBACK;
  }
  const base = trimmed
    .replace(
      /-(?:UltraLight|Thin|ExtraLight|Light|Regular|Book|Medium|Semibold|SemiBold|DemiBold|Bold|ExtraBold|Heavy|Black|Italic|Oblique|Condensed|Compressed|Expanded|Extended|Display|Text|MT)$/i,
      ''
    )
    .trim();
  const needsQuotes = /[\s'"]/.test(base);
  const formatted = needsQuotes ? `"${base.replace(/"/g, '\\"')}"` : base;
  return `${formatted}, ${SYSTEM_FONT_FALLBACK}`;
}

function applyInitConfig(config: InitMessage) {
  applyHostTheme(config.theme);
  const root = document.documentElement;
  if (config.theme.processingRgb) root.style.setProperty('--processing-rgb', config.theme.processingRgb);
  root.style.setProperty('--font-family-light', toCssFontFamily(config.fonts.fontFamily));
  root.style.setProperty('--font-family-medium', toCssFontFamily(config.fonts.fontFamilyMedium));
  root.style.setProperty('--font-family-bold', toCssFontFamily(config.fonts.fontFamilyBold));
}

export default function App() {
  const [meeting, setMeeting] = useState<MeetingInfo | null>(null);
  const [initialized, setInitialized] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const handleInit = useCallback((config: InitMessage) => {
    applyInitConfig(config);
    setInitialized(true);
  }, []);

  useEffect(() => {
    registerInitHandler(handleInit);
    registerThemeHandler((theme, fonts) => applyInitConfig({ theme, fonts }));
    registerMeetingHandler(setMeeting);
    notifyReady();
  }, [handleInit]);

  const calendarSource = meeting?.calendarName ?? null;
  const attendees = meeting?.calendarAttendees ?? [];

  // The attendee chip row wraps at an unpredictable number of lines
  // depending on how many attendees there are and how long their names
  // are, so height can't be derived from fixed per-row constants the way
  // the other mini panels do. `.mini-panel` (below) has no fixed height of
  // its own, so it always sizes to its actual rendered content; measuring
  // it directly after each render is the only accurate way to know how
  // tall the host window needs to be.
  useLayoutEffect(() => {
    if (!initialized) return;
    const el = panelRef.current;
    if (!el) return;
    const contentHeight = Math.ceil(el.getBoundingClientRect().height);
    requestResize(PANEL_WIDTH, contentHeight);
  }, [initialized, meeting]);

  const title = meeting?.displayTitle || 'Meeting/call detected';
  const actionLabel = meeting ? 'Join call' : 'Loading...';
  // `displayTitle` falls back to `appName` when there's no calendar-derived
  // title (e.g. an ad-hoc call with no calendar match), so the badge would
  // otherwise show the exact same string as the title right next to it.
  // Only render the badge when it adds information beyond the title.
  const detectionBadgeLabel = meeting && meeting.appName !== title ? meeting.appName : null;

  return (
    <div className="basil-webkit-window-frame">
      <div className="mini-panel basil-webkit-window-surface" role="region" aria-label="Meeting/call detected" ref={panelRef}>
      <div className="mini-panel-header">
        <div className="mini-panel-header-title">
          <span className="meeting-status-dot" aria-hidden="true" />
          <span>Meeting/call detected</span>
        </div>
        {detectionBadgeLabel && (
          <span className="meeting-detection-badge" title={`Detected via ${detectionBadgeLabel}`}>
            {detectionBadgeLabel}
          </span>
        )}
      </div>

      <div className="mini-panel-body">
        <div className="meeting-copy">
          <div className="meeting-title" title={title}>{title}</div>
          {!meeting && <div className="meeting-detail">Preparing meeting prompt...</div>}
          {calendarSource && (
            <div className="meeting-detail" title={`Calendar: ${calendarSource}`}>
              Calendar: {calendarSource}
            </div>
          )}
          {attendees.length > 0 && (
            <div className="meeting-attendees-field">
              {attendees.map((name, index) => (
                <span key={`${name}-${index}`} className="meeting-attendee-chip">{name}</span>
              ))}
            </div>
          )}
        </div>

        <div className="meeting-actions">
          <button
            type="button"
            className="meeting-primary-action"
            onClick={() => startMeeting()}
            disabled={!meeting}
          >
            {actionLabel}
          </button>
          <button
            type="button"
            className="meeting-secondary-action"
            onClick={() => dismissMeeting()}
            disabled={!meeting}
          >
            Dismiss
          </button>
        </div>
      </div>
      </div>
    </div>
  );
}
