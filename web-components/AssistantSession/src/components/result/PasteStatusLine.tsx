import type { AssistantSessionPasteOutcome } from '../../bridge/types';

export function pasteStatusText(outcome: AssistantSessionPasteOutcome, applicationName: string | null): string {
  switch (outcome) {
    case 'pasted':
      return applicationName ? `Pasted into ${applicationName}` : 'Pasted';
    case 'shown':
      return 'Not pasted (shown here)';
    case 'switchedApps':
      return applicationName ? `Not pasted (you left ${applicationName})` : 'Not pasted (you switched apps)';
    case 'targetUnavailable':
      return applicationName ? `Not pasted (couldn't return to ${applicationName})` : 'Not pasted (no app to paste into)';
  }
}

export function PasteStatusLine({
  outcome,
  applicationName,
}: {
  outcome: AssistantSessionPasteOutcome | null;
  applicationName: string | null;
}) {
  if (!outcome) return null;
  const variant = outcome === 'pasted' ? 'pasted' : 'skipped';
  const text = pasteStatusText(outcome, applicationName);
  return (
    <p className={`assistant-session-result__paste-status assistant-session-result__paste-status--${variant}`} role="status" title={text}>
      {text}
    </p>
  );
}
