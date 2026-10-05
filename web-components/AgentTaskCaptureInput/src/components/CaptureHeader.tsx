import { useLayoutEffect, useRef } from 'react';
import type { CaptureSnapshot } from '../types';
import {
  cancelCapture,
  enterTextEntryMode,
  enterVoiceMode,
  reportCaptureHeaderExtent,
  showHistory,
} from '../services/bridge';
import paprikaIcon from '../assets/paprika-icon.png';

interface Props {
  snapshot: CaptureSnapshot;
  displayName: string;
}

// Inline SF-Symbol-equivalent glyphs. No pre-built SVG primitive exists in
// this codebase for any of these three shapes — see
// `02_Prior_Art_Manifest.md` section 2.3 for why hand-drawing is the
// established, narrow exception here rather than a forbidden approximation.
function CancelGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <circle cx="8" cy="8" r="7" fill="currentColor" />
      <path d="M5.5 5.5l5 5M10.5 5.5l-5 5" stroke="var(--background-primary)" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}

function HistoryGlyph() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M8 1a7 7 0 1 0 7 7" />
      <path d="M8 1v2M8 4.5V8l3 1.8" />
      <path d="M15 3.5v3h-3" />
    </svg>
  );
}

function MicGlyph() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5.5" y="1" width="5" height="8" rx="2.5" />
      <path d="M3.5 7a4.5 4.5 0 0 0 9 0" />
      <line x1="8" y1="11.5" x2="8" y2="14" />
      <line x1="5.5" y1="14" x2="10.5" y2="14" />
    </svg>
  );
}

function KeyboardGlyph() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="1" y="4" width="14" height="9" rx="1.5" />
      <line x1="3.5" y1="7" x2="3.5" y2="7" />
      <line x1="6" y1="7" x2="6" y2="7" />
      <line x1="8.5" y1="7" x2="8.5" y2="7" />
      <line x1="11" y1="7" x2="11" y2="7" />
      <line x1="4" y1="10.5" x2="12" y2="10.5" />
    </svg>
  );
}

export default function CaptureHeader({ snapshot, displayName }: Props) {
  const headerRef = useRef<HTMLDivElement>(null);
  const isTextEntry = snapshot.inputModality === 'text';

  useLayoutEffect(() => {
    const header = headerRef.current;
    if (!header) return;

    const reportExtent = () => {
      const frame = header.closest<HTMLElement>('.basil-webkit-window-frame');
      if (!frame) return;

      const frameRect = frame.getBoundingClientRect();
      const headerRect = header.getBoundingClientRect();
      reportCaptureHeaderExtent(headerRect.bottom - frameRect.top);
    };

    reportExtent();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(reportExtent);
    observer?.observe(header);
    return () => observer?.disconnect();
  }, []);

  return (
    <div ref={headerRef} className="capture-header">
      <div className="capture-header__leading">
        <button
          type="button"
          className="capture-header__icon-button"
          onClick={() => cancelCapture()}
          title="Cancel task"
          aria-label="Cancel task"
        >
          <CancelGlyph />
        </button>
        {/* Matches the archived `AgentTaskCaptureWidget.swift`'s leading
            `VStack(spacing: 3) { Button; Color.clear.frame(width: 16, height: 16) }`
            exactly — this spacer, not any CSS padding, is what gives the
            header row its correct height in the native widget. */}
        <div className="capture-header__leading-spacer" aria-hidden="true" />
      </div>
      <div className="capture-header__center">
        {/* Matches the archived widget's `ZStack { HStack { ... }.offset(x: -8) } }`
            exactly: the visual -8px nudge belongs on this inner wrapper, not
            on `.capture-header__center` itself — that outer flex item's own
            hit-test box must stay put, or it overlaps the leading button. */}
        <div className="capture-header__center-inner">
          <img className="capture-header__team-icon" src={paprikaIcon} alt="" aria-hidden="true" />
          <span>{displayName}</span>
        </div>
      </div>
      <div className="capture-header__trailing">
        <button
          type="button"
          className="capture-header__icon-button capture-header__icon-button--secondary"
          onClick={() => showHistory()}
          title="Show task history"
          aria-label="Show task history"
        >
          <HistoryGlyph />
        </button>
        <button
          type="button"
          className="capture-header__icon-button capture-header__icon-button--secondary"
          onClick={() => (isTextEntry ? enterVoiceMode() : enterTextEntryMode())}
          title={isTextEntry ? 'Switch to voice capture' : 'Switch to text entry'}
          aria-label={isTextEntry ? 'Switch to voice capture' : 'Switch to text entry'}
        >
          {isTextEntry ? <MicGlyph /> : <KeyboardGlyph />}
        </button>
      </div>
    </div>
  );
}
