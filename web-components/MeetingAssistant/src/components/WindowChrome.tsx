import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { closeWindow, minimizeWindow, reportChromeHeight } from '../bridge/meetingBridge';

interface WindowChromeProps {
  title: string;
  subtitle?: string;
  titleVariant?: 'callout' | 'body' | 'headline';
  featureIcon?: 'analysis' | 'microphone';
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  isRecording: boolean;
  trailing?: ReactNode;
  bubble?: ReactNode;
  hideWindowControls?: boolean;
  canCollapse?: boolean;
}

export default function WindowChrome({
  title,
  subtitle,
  titleVariant = 'body',
  featureIcon = 'analysis',
  isCollapsed,
  onToggleCollapse,
  isRecording,
  trailing,
  bubble,
  hideWindowControls = false,
  canCollapse = true,
}: WindowChromeProps) {
  const headerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const header = headerRef.current;
    if (!header) return;

    const publishHeight = () => reportChromeHeight(header.offsetHeight);

    publishHeight();
    window.addEventListener('resize', publishHeight);
    const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(publishHeight);
    resizeObserver?.observe(header);

    return () => {
      window.removeEventListener('resize', publishHeight);
      resizeObserver?.disconnect();
    };
  });

  return (
    <div ref={headerRef} className={`meeting-window-chrome${bubble ? ' meeting-window-chrome--with-bubble' : ''}${isCollapsed ? ' meeting-window-chrome--collapsed' : ''}`} data-drag-handle="true">
      {(!hideWindowControls || canCollapse) && (
        <div className="meeting-window-chrome-actions">
          {!hideWindowControls && (
            <>
              <button type="button" className="meeting-chrome-button" onClick={closeWindow} aria-label="Close">
                <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                  <circle cx="11" cy="11" r="10" fill="var(--meeting-window-control-fill)" />
                  <line x1="7.5" y1="7.5" x2="14.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                  <line x1="14.5" y1="7.5" x2="7.5" y2="14.5" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
              <button type="button" className="meeting-chrome-button" onClick={minimizeWindow} aria-label="Minimize">
                <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                  <circle cx="11" cy="11" r="10" fill="var(--meeting-window-control-fill)" />
                  <line x1="6.5" y1="11" x2="15.5" y2="11" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
              </button>
            </>
          )}
          {canCollapse && (
            <button type="button" className="meeting-chrome-button" onClick={onToggleCollapse} aria-label={isCollapsed ? 'Expand' : 'Collapse'} aria-pressed={isCollapsed}>
              <svg width="20" height="20" viewBox="0 0 22 22" aria-hidden="true">
                <circle cx="11" cy="11" r="10" fill="var(--meeting-window-control-fill)" />
                <path className={`meeting-window-collapse-chevron${isCollapsed ? ' is-collapsed' : ''}`} d="M7 9l4 4 4-4" fill="none" stroke="var(--secondary)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
        </div>
      )}
      {featureIcon === 'microphone' ? (
        <svg className="meeting-window-feature-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.35" aria-hidden="true">
          <circle cx="10" cy="10" r="8" />
          <rect x="7.8" y="4.8" width="4.4" height="7.2" rx="2.2" />
          <path d="M5.8 9.5a4.2 4.2 0 0 0 8.4 0M10 13.7v2.1M7.8 15.8h4.4" strokeLinecap="round" />
        </svg>
      ) : (
        <svg className="meeting-window-feature-icon" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.35" aria-hidden="true">
          <circle cx="10" cy="10" r="8" />
          <path d="M10 5.5v9M7.4 8.2v3.6M12.6 8.2v3.6" strokeLinecap="round" />
        </svg>
      )}
      <div className="meeting-window-chrome-status">
        <span className={`meeting-window-chrome-title meeting-window-chrome-title--${titleVariant}`}>{title}</span>
        <span className={`meeting-window-chrome-subtitle${isRecording ? ' is-recording' : ''}${subtitle ? '' : ' is-empty'}`}>
          {subtitle || '\u00A0'}
        </span>
      </div>
      {!isCollapsed && trailing}
      {bubble && (
        <div className="meeting-window-status-bubble" aria-hidden="true">
          {bubble}
        </div>
      )}
    </div>
  );
}
