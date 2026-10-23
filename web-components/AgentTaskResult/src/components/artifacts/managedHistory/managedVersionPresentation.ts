import type { ManagedFileVersion } from './managedHistoryApi';
import type { AgentTaskRunFocusSummary } from '../../run/agentTaskRunFocus';

/**
 * Human-readable label for one entry in the managed-version dropdown.
 * Index 0 is always the most recent recorded version ("Current"). Older
 * entries are labeled with the ordinal of the run that produced them when
 * that run is present in `runs` (matched by `agentTaskId`); otherwise they
 * fall back to a position-based ordinal counted from the oldest version.
 */
export function managedVersionLabel(
  versions: ManagedFileVersion[],
  index: number,
  runs: AgentTaskRunFocusSummary[] | undefined,
): string {
  if (index === 0) return 'Current';
  const version = versions[index];
  const ordinal = runs?.find(run => run.id === version.agentTaskId)?.ordinal ?? versions.length - index;
  return `Run ${ordinal} · ${version.operation} · ${new Date(version.createdAt).toLocaleString()}`;
}

/**
 * Wraps raw HTML content in a locked-down document for `<iframe srcDoc>`
 * rendering. No script execution, no external network access (relative
 * asset references will not resolve) — this is a raw-markup preview, not a
 * live render of the artifact's dependencies. Shared by the sidebar's HTML
 * "Render" mode and, for historical versions only, by LocalWebPreviewApp.
 */
export function sandboxedHtmlDocument(rawHtml: string): string {
  return (
    '<!doctype html><html><head>'
    + '<meta charset="utf-8">'
    + '<meta http-equiv="Content-Security-Policy" '
    + 'content="default-src \'none\'; style-src \'unsafe-inline\'; img-src data:; font-src data:;">'
    + '<style>body{font-family:sans-serif;padding:12px;color:#111;}</style>'
    + `</head><body>${rawHtml}</body></html>`
  );
}
