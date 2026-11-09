/** The approval card leads with the agent's explanation; the command itself shows only this much until the user expands it. */
export const COMMAND_PREVIEW_CHARS = 80;

/** First line of the command, cut to the preview length. `previewable` is true when anything is hidden behind it. */
export function previewCommand(commandText: string): { preview: string; previewable: boolean } {
  const firstLine = commandText.split('\n', 1)[0];
  const truncated = firstLine.length > COMMAND_PREVIEW_CHARS;
  const previewable = truncated || firstLine.length < commandText.length;
  if (!previewable) return { preview: commandText, previewable: false };
  const head = truncated ? firstLine.slice(0, COMMAND_PREVIEW_CHARS).trimEnd() : firstLine;
  return { preview: `${head}…`, previewable: true };
}
