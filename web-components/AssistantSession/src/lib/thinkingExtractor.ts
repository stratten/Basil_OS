/** Port of `ThinkingExtractor.split` for persisted history rows that store raw `<think>` tags. */
export function splitThinking(rawText: string): { thinking: string | null; content: string } {
  const openTag = '<think>';
  const closeTag = '</think>';
  if (!rawText.includes(openTag)) {
    return { thinking: null, content: rawText };
  }

  let thinking = '';
  let content = '';
  let remaining = rawText;

  while (remaining.includes(openTag)) {
    const start = remaining.indexOf(openTag);
    content += remaining.slice(0, start);
    const afterOpen = remaining.slice(start + openTag.length);
    const end = afterOpen.indexOf(closeTag);
    if (end >= 0) {
      const segment = afterOpen.slice(0, end);
      thinking += (thinking.length === 0 ? '' : '\n\n') + segment;
      remaining = afterOpen.slice(end + closeTag.length);
    } else {
      thinking += (thinking.length === 0 ? '' : '\n\n') + afterOpen;
      remaining = '';
      break;
    }
  }

  content += remaining;
  const trimmedThinking = thinking.trim();
  return {
    thinking: trimmedThinking.length === 0 ? null : trimmedThinking,
    content: content.trim(),
  };
}

export function stripThinking(rawText: string): string {
  return splitThinking(rawText).content;
}
