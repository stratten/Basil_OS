export const ATTACHMENTS_LABEL = 'Attachments / References';
export const ATTACH_BUTTON_LABEL = 'Attach files or folders';
export const DROP_OVERLAY_TEXT = 'Drop files here';
export const EMPTY_ATTACHMENTS_TEXT = 'Nothing attached yet. Drop files or folders here, or choose Add.';
export const READ_ONLY_EMPTY_TEXT = 'Nothing is attached.';

export interface AttachmentEntry {
  /** Stable React key; unique within one list. */
  key: string;
  /** Absolute local path. Shown as the tooltip. */
  path: string;
  /** Display name; defaults to the last path segment. */
  name?: string;
  /** Folder glyph when true; defaults to a trailing-slash heuristic. */
  isDirectory?: boolean;
  /** Queued locally and not yet saved; drawn with a dashed outline. */
  pending?: boolean;
  /** Accessible name of the remove button; defaults to `Remove <name>`. */
  removeLabel?: string;
  /** Tooltip override; defaults to the path. */
  title?: string;
  /** A connection (MCP) tied to the host rather than a file: drawn with a connection glyph, with no open or Reveal in Finder. Its `path` is not a file path; it only has to be non-empty (hosts pass the connection id). */
  kind?: 'connection';
}

export function attachmentBasename(path: string): string {
  const trimmed = path.replace(/\/+$/, '');
  const segments = trimmed.split('/');
  return segments[segments.length - 1] || path;
}

export function attachmentIsDirectory(entry: Pick<AttachmentEntry, 'path' | 'isDirectory'>): boolean {
  return entry.isDirectory ?? entry.path.endsWith('/');
}

/** Appends `added` to `existing`, dropping blanks and duplicates while keeping order; `limit` caps the result. */
export function mergeAttachmentPaths(existing: readonly string[], added: readonly string[], limit?: number): string[] {
  const cleaned = added.filter((path) => typeof path === 'string' && path.trim() !== '');
  const merged = [...new Set([...existing, ...cleaned])];
  return limit === undefined ? merged : merged.slice(0, limit);
}

export function pathEntries(paths: readonly string[]): AttachmentEntry[] {
  return paths.map((path, index) => ({ key: `${path}#${index}`, path }));
}
