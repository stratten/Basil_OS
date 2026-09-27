/** Normalizes raw think content into paragraph-separated markdown, ported from AssistantSessionWidget_SharedComponents.swift. */
export function normalizedThinkingMarkdown(content: string): string {
  if (content.includes('\n\n')) {
    return content;
  }
  if (content.includes('\n')) {
    return content
      .split('\n')
      .map((line) => line.trim())
      .filter((line) => line.length > 0)
      .join('\n\n');
  }
  const sentenceBoundary = /(?<=[.!?])\s+(?=[A-Z"'(])/g;
  return content.split(sentenceBoundary).join('\n\n');
}
