import { useLayoutEffect, useRef } from 'react';
import { usePresenceTransition } from '../app/usePresenceTransition';
import CrossfadeStack from './CrossfadeStack';
import { normalizeProgressStepText } from './result/progressStepText';

interface Props {
  isProcessing: boolean;
  currentStep?: string;
  isStepComplete?: boolean;
}

export default function ProgressOverlay({ isProcessing, currentStep, isStepComplete }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const latestStepRef = useRef(currentStep);
  const latestCompleteRef = useRef(isStepComplete);
  const presence = usePresenceTransition(Boolean(isProcessing && currentStep));
  if (currentStep) {
    latestStepRef.current = currentStep;
    latestCompleteRef.current = isStepComplete;
  }

  useLayoutEffect(() => {
    const overlay = overlayRef.current;
    const contentArea = overlay?.closest('.content-area');
    if (!(overlay instanceof HTMLElement) || !(contentArea instanceof HTMLElement)) {
      return;
    }

    const updateClearance = () => {
      contentArea.style.setProperty(
        '--progress-overlay-clearance',
        `${overlay.offsetHeight + 2}px`,
      );
    };
    updateClearance();

    const observer = new ResizeObserver(updateClearance);
    observer.observe(overlay);
    return () => {
      observer.disconnect();
      contentArea.style.removeProperty('--progress-overlay-clearance');
    };
  }, [isProcessing, currentStep]);

  if (!presence.shouldRender || !latestStepRef.current) return null;

  const displayStep = normalizeProgressStepText(latestStepRef.current);

  return (
    <div
      ref={overlayRef}
      className="progress-overlay"
      data-presence-phase={presence.phase}
      aria-hidden={presence.phase !== 'present'}
      onTransitionEnd={presence.completeTransition}
    >
      <CrossfadeStack
        contentKey={`${displayStep}:${latestCompleteRef.current ? 'complete' : 'active'}`}
        className="progress-step-stack"
      >
      <div className="progress-step">
        <span className={`progress-step-icon ${latestCompleteRef.current ? 'complete' : 'active'}`}>
          {latestCompleteRef.current ? (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="var(--success-base)">
              <path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0zm3.41 5.09a.75.75 0 0 0-1.06-.04L7.2 8.04 5.64 6.59a.75.75 0 1 0-1.02 1.1l2.1 1.95a.75.75 0 0 0 1.04-.03l3.65-3.46a.75.75 0 0 0-.04-1.06z"/>
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="var(--secondary)" strokeWidth="1.5" strokeDasharray="3 2">
              <circle cx="8" cy="8" r="7" />
            </svg>
          )}
        </span>
        <span style={{
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          overflowWrap: 'anywhere',
        }}>
          {displayStep}
        </span>
      </div>
      </CrossfadeStack>
    </div>
  );
}
