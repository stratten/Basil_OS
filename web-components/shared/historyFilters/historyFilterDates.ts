function parseLocalDay(day: string): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!match) return null;
  return [Number(match[1]), Number(match[2]) - 1, Number(match[3])];
}

/** The first instant of a local calendar day ("YYYY-MM-DD"), as the ISO instant the backend compares against. */
export function startOfLocalDayIso(day: string): string | undefined {
  const parts = parseLocalDay(day);
  return parts ? new Date(parts[0], parts[1], parts[2], 0, 0, 0, 0).toISOString() : undefined;
}

/** The last instant of a local calendar day ("YYYY-MM-DD"), as the ISO instant the backend compares against. */
export function endOfLocalDayIso(day: string): string | undefined {
  const parts = parseLocalDay(day);
  return parts ? new Date(parts[0], parts[1], parts[2], 23, 59, 59, 999).toISOString() : undefined;
}

/** How many of a filter set's conditions are narrowing the list: the truthy entries, with text conditions trimmed by the caller. */
export function countActiveFilters(conditions: readonly unknown[]): number {
  return conditions.filter(Boolean).length;
}
