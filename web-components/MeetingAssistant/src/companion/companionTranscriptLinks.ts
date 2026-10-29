import type { TranscriptLineDTO } from '../bridge/types';
import type { CompanionItem, TranscriptRange } from './types';

/** How far outside a range a transcript line may sit and still count as part of it. The Companion's ranges come from the recorder's segment times and the transcript lines carry the same timeline in seconds, so this only absorbs re-transcription drift at the edges. */
export const LINK_TOLERANCE_SECONDS = 0.25;

/** When a range overlaps no line at all (an item with no source turns, or a gap in the transcript), the nearest line is used only if it is this close. Farther than that the link would point somewhere unrelated. */
export const LINK_NEAREST_MAX_SECONDS = 20;

/** The only part of a transcript line the mapping needs. */
export interface TimedTranscriptRow {
  id: string;
  start: number | null;
  end: number | null;
}

export function timedRowFromLine(line: TranscriptLineDTO): TimedTranscriptRow {
  return { id: line.id, start: line.timelineStartSeconds, end: line.timelineEndSeconds ?? line.timelineStartSeconds };
}

function rowBounds(row: TimedTranscriptRow): { start: number; end: number } | null {
  if (row.start === null || !Number.isFinite(row.start)) return null;
  const end = row.end !== null && Number.isFinite(row.end) ? Math.max(row.start, row.end) : row.start;
  return { start: row.start, end };
}

/** Ids of the lines that make up the range, in transcript order. Lines overlap when their span touches the range widened by the tolerance; with no overlap the single nearest line within the maximum distance is used, and with none close enough the result is empty. Lines without timeline seconds never match. */
export function spanRowIds(rows: TimedTranscriptRow[], range: Pick<TranscriptRange, 'start' | 'end'>): string[] {
  const low = Math.min(range.start, range.end) - LINK_TOLERANCE_SECONDS;
  const high = Math.max(range.start, range.end) + LINK_TOLERANCE_SECONDS;
  const overlapping: string[] = [];
  let nearest: { id: string; distance: number } | null = null;
  const middle = (range.start + range.end) / 2;
  for (const row of rows) {
    const bounds = rowBounds(row);
    if (bounds === null) continue;
    if (bounds.end >= low && bounds.start <= high) {
      overlapping.push(row.id);
      continue;
    }
    const distance = Math.min(Math.abs(bounds.start - middle), Math.abs(bounds.end - middle));
    if (nearest === null || distance < nearest.distance) nearest = { id: row.id, distance };
  }
  if (overlapping.length > 0) return overlapping;
  return nearest !== null && nearest.distance <= LINK_NEAREST_MAX_SECONDS ? [nearest.id] : [];
}

/** The line a chip for the range sits on: the last line of the span, which is where the conversation was when the Companion spoke up. */
export function anchorRowId(rows: TimedTranscriptRow[], range: Pick<TranscriptRange, 'start' | 'end'>): string | null {
  const ids = spanRowIds(rows, range);
  return ids.length > 0 ? ids[ids.length - 1] : null;
}

/** Which items each line carries a chip for, as line id to item ids in arrival order. Dismissed items and items that map to no line are left out. */
export function chipsByRow(rows: TimedTranscriptRow[], items: CompanionItem[]): Map<string, string[]> {
  const chips = new Map<string, string[]>();
  const ordered = items.filter((item) => !item.dismissed).sort((a, b) => a.seq - b.seq);
  for (const item of ordered) {
    const anchor = anchorRowId(rows, item.transcript_range);
    if (anchor === null) continue;
    const existing = chips.get(anchor);
    if (existing) existing.push(item.id);
    else chips.set(anchor, [item.id]);
  }
  return chips;
}
