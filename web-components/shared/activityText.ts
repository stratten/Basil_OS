export function normalizeProgressStepText(text: string): string {
  return text
    .replace(/\\r\\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\n');
}

export const ACTIVITY_TRAIL_LIMIT = 3;

export type ActivityTextEntry = {
  type: string;
  content: string;
  summary?: string;
  detail_kind?: string;
  metadata?: {
    raw_detail?: boolean;
    progress_step?: string;
  };
};

type SummaryBearing = { summary?: string };

export function looksLikeRawPayload(text: string): boolean {
  const trimmed = text.trim();
  return (
    trimmed.startsWith('{')
    || trimmed.startsWith('[')
    || trimmed.includes('"action"')
    || trimmed.includes('"action_input"')
    || trimmed.includes("'action_input'")
    || trimmed.includes('"raw_messages"')
    || trimmed.includes("'raw_messages'")
  );
}

export function conciseExecutionStepText(text: string, detail?: SummaryBearing): string {
  const summary = normalizeProgressStepText(detail?.summary || '').trim();
  if (summary && !looksLikeRawPayload(summary)) {
    return summary.length > 180 ? `${summary.slice(0, 177)}...` : summary;
  }

  const normalized = normalizeProgressStepText(text).trim();
  const firstLine = normalized.split('\n').find((line) => line.trim().length > 0)?.trim() || normalized;
  const payloadIndex = Math.min(
    ...[" {'", ' {"', '\t{', '\t['].map((marker) => {
      const index = firstLine.indexOf(marker);
      return index >= 0 ? index : Number.POSITIVE_INFINITY;
    }),
  );
  const label = Number.isFinite(payloadIndex) ? firstLine.slice(0, payloadIndex).trim() : firstLine;
  return label.length > 180 ? `${label.slice(0, 177)}...` : label;
}

export function timelineEntryReadableText(entry: ActivityTextEntry): string {
  return conciseExecutionStepText(entry.content || '', entry as SummaryBearing);
}

function hasReadableProgress(entry: ActivityTextEntry): boolean {
  if (entry.type === 'thinking') return false;
  if (entry.metadata?.raw_detail === true) return false;

  const progressStep = entry.metadata?.progress_step;
  const hasProgressStep = typeof progressStep === 'string' && progressStep.trim().length > 0;
  const isProgressDetailKind = entry.detail_kind === 'step_note' || entry.detail_kind === 'step_complete';
  const isProgressType = entry.type === 'step' || entry.type === 'tool_complete' || entry.type === 'tool_start';

  if (!hasProgressStep && !isProgressDetailKind && !isProgressType) return false;

  return timelineEntryReadableText(entry).trim().length > 0;
}

export function selectActivityTrail<T extends ActivityTextEntry>(
  timeline: T[],
  limit = ACTIVITY_TRAIL_LIMIT,
): T[] {
  const readable = timeline.filter(hasReadableProgress);
  return limit > 0 ? readable.slice(-limit) : readable;
}

export function activityStatusSnapshot(timeline: ActivityTextEntry[]): string | undefined {
  const [latest] = selectActivityTrail(timeline, 1);
  if (!latest) return undefined;
  const text = timelineEntryReadableText(latest).trim();
  return text ? text : undefined;
}
