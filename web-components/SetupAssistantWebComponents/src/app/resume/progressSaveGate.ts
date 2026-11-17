// The as-you-go save and the Done and Skip posts all write the same backend file. A save that is still in flight when Done or Skip is chosen must land first, or it could arrive afterward and turn a finished setup back into one waiting to be resumed.

let inFlight: Promise<unknown> | null = null

/** Remembers a save that has started so Done and Skip can wait for it. */
export function trackProgressSave<T>(save: Promise<T>): Promise<T> {
  const tracked: Promise<unknown> = save.catch(() => undefined)
  inFlight = tracked
  void tracked.then(() => {
    if (inFlight === tracked) inFlight = null
  })
  return save
}

/** Runs `action` at once when no save is in flight, otherwise right after the save settles. */
export function afterProgressSave(action: () => void): void {
  if (inFlight === null) {
    action()
    return
  }
  void inFlight.then(action)
}
