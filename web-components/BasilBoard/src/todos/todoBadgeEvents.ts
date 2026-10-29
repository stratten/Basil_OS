// A tiny in-page signal so the Board rail refreshes its To-Do counts right after the To-Do view changes something,
// instead of waiting for the next poll. The To-Do view and the rail share one JavaScript context in the main Board window;
// a change made in the detached To-Dos window reaches the rail through the poll and the window-focus refresh instead.

const listeners = new Set<() => void>();

export function notifyTodoCountsChanged(): void {
  for (const listener of [...listeners]) listener();
}

export function subscribeTodoCountsChanged(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
