function parseTimeMs(value: string): number {
  const trimmed = value.trim();
  const amount = Number.parseFloat(trimmed);
  if (!Number.isFinite(amount)) return 0;
  return trimmed.endsWith('ms') ? amount : amount * 1000;
}

function longestTransitionMs(element: HTMLElement): number {
  const style = window.getComputedStyle(element);
  const durations = style.transitionDuration.split(',');
  const delays = style.transitionDelay.split(',');
  return durations.reduce((longest, duration, index) => {
    const delay = delays[index % delays.length] ?? '0s';
    return Math.max(longest, parseTimeMs(duration) + parseTimeMs(delay));
  }, 0);
}

export function settleWhenUntransitioned(element: HTMLElement, onSettle: () => void): () => void {
  if (longestTransitionMs(element) <= 0) {
    onSettle();
    return () => undefined;
  }
  const frame = window.requestAnimationFrame(() => {
    if (typeof element.getAnimations === 'function' && element.getAnimations().length === 0) onSettle();
  });
  return () => window.cancelAnimationFrame(frame);
}
