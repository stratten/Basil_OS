import { useEffect, useId, useState } from 'react';
import { openAppSettings } from '../bridge/meetingBridge';
import { adviceChipLabel, formatAdviceDuration, mostSevere } from './resourceAdvicePresentation';
import { useResourceAdvice } from './useResourceAdvice';

const CLOCK_REFRESH_MS = 30_000;

export interface ResourceAdviceProps {
  port: number;
  recording: boolean;
  thermalState?: string | null;
}

/** A chip that appears only while a recording is struggling, with a panel that says what is wrong and what to do about it. */
export default function ResourceAdvice({ port, recording, thermalState }: ResourceAdviceProps) {
  const { advice, dismiss } = useResourceAdvice({ port, recording, thermalState });
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const panelId = useId();
  const hasAdvice = advice.length > 0;

  useEffect(() => {
    if (!hasAdvice) {
      setOpen(false);
      return undefined;
    }
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), CLOCK_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [hasAdvice]);

  if (!hasAdvice) return null;
  const severity = mostSevere(advice);

  return (
    <div
      className="meeting-resource-advice"
      aria-live="polite"
      onKeyDown={(event) => {
        if (event.key === 'Escape' && open) {
          event.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        className={`meeting-resource-chip meeting-resource-chip--${severity}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="meeting-resource-dot" aria-hidden="true" />
        <span className="meeting-resource-chip-label">{adviceChipLabel(advice)}</span>
      </button>
      {open && (
        <ul id={panelId} className="meeting-resource-panel" aria-label="Recording performance advice">
          {advice.map((item) => (
            <li key={item.id} className={`meeting-resource-item meeting-resource-item--${item.severity}`}>
              <div className="meeting-resource-item-heading">
                <strong className="meeting-resource-item-title">{item.title}</strong>
                <span className="meeting-status-message">{formatAdviceDuration(item.raised_at, now)}</span>
              </div>
              <p className="meeting-resource-item-detail">{item.detail}</p>
              <div className="meeting-resource-item-actions">
                {item.action === 'open_settings' && (
                  <button type="button" className="meeting-record-button" onClick={openAppSettings}>
                    Open Settings
                  </button>
                )}
                <button type="button" className="meeting-record-button" onClick={() => void dismiss(item.id)}>
                  Dismiss
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
