import type { TranscriptLineDTO } from '../bridge/types';

export interface TranscriptDisplayRow {
  line: TranscriptLineDTO;
  isGroupLeader: boolean;
  label: string | null;
  color: string | null;
}

/**
 * Groups consecutive lines from the same source/speaker so the UI (and the
 * plain-text formatters below) only need to render one attribution badge per
 * turn instead of repeating it on every line.
 */
export function buildTranscriptRows(lines: TranscriptLineDTO[]): TranscriptDisplayRow[] {
  let previousGroup: string | null = null;
  return lines.filter((line) => line.text.trim().length > 0).map((line) => {
    const presentation = attributionPresentation(line);
    const group = `${line.source ?? ''}|${line.speakerId ?? ''}`;
    const isGroupLeader = group !== previousGroup;
    previousGroup = group;
    return { line, isGroupLeader, ...presentation };
  });
}

function attributionPresentation(line: TranscriptLineDTO): Pick<TranscriptDisplayRow, 'label' | 'color'> {
  if (line.source) {
    return {
      label: line.source === 'Microphone' ? 'Microphone' : 'System Audio',
      color: line.source === 'Microphone' ? 'var(--primary)' : 'var(--success-base)',
    };
  }
  const speakerNumber = parseSpeakerNumber(line.speakerId);
  if (speakerNumber !== null) {
    const colors = ['var(--secondary)', 'var(--success-base)', 'var(--warning-base)', '#5856D6', '#AA3278'];
    return { label: `Speaker ${speakerNumber}`, color: colors[(speakerNumber - 1) % colors.length] };
  }
  return { label: null, color: null };
}

function parseSpeakerNumber(speakerId: string | null): number | null {
  if (!speakerId) return null;
  const match = speakerId.match(/(\d+)$/);
  if (!match) return null;
  const parsed = Number(match[1]);
  return /^speaker/i.test(speakerId) ? parsed + 1 : parsed > 0 ? parsed : null;
}

export function formatTranscriptTimestamp(value: string | null) {
  if (!value) return '[00:00]';
  const parts = value.split(':').map((part) => Number(part));
  if (parts.length === 3) {
    const [hours, minutes, seconds] = parts;
    return hours > 0 ? `[${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}]` : `[${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}]`;
  }
  return `[${value}]`;
}

interface TranscriptTextBlock {
  header: string;
  lines: string[];
}

/**
 * Renders grouped transcript rows as legible plain text: one `[timestamp]
 * Speaker` header per turn followed by its indented line(s), with a blank
 * line between turns/speaker swaps so the result is readable outside the
 * app (clipboard, exported markdown) instead of one run-on wall of text.
 */
export function formatTranscriptForCopy(rows: TranscriptDisplayRow[]): string {
  const blocks: TranscriptTextBlock[] = [];
  let current: TranscriptTextBlock | null = null;
  for (const row of rows) {
    const text = row.line.text.trim();
    if (!text) continue;
    if (row.isGroupLeader || !current) {
      if (current) blocks.push(current);
      const timestamp = formatTranscriptTimestamp(row.line.displayStart);
      current = { header: row.label ? `${timestamp} ${row.label}` : timestamp, lines: [text] };
    } else {
      current.lines.push(text);
    }
  }
  if (current) blocks.push(current);
  return blocks.map(renderTranscriptBlock).join('\n\n');
}

function renderTranscriptBlock(block: TranscriptTextBlock): string {
  return [block.header, ...block.lines.map((line) => `    ${line}`)].join('\n');
}
