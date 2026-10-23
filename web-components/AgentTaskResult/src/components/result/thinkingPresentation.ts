export function shouldAutoCollapseThinking(
  _previousResponseStreaming: boolean,
  responseStreaming: boolean,
  alreadyHandled: boolean,
): boolean {
  return !alreadyHandled && responseStreaming;
}
