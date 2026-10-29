// Todo due dates and completed dates are always set from an <input type="date">
// as `${value}T00:00:00Z` (see TodoDetailPane.tsx), so the only meaningful
// information they carry is the YYYY-MM-DD calendar day -- not a real UTC
// instant. Treating them as instants (via `new Date(value)`) causes two bugs:
// a due date of "today" reads as already overdue in negative-UTC-offset
// timezones, and formatting the same value with vs. without a UTC round-trip
// produces a 1-day mismatch between the sidebar and the detail pane. These
// helpers always operate on the date-only substring instead.

export function todoDateOnly(value: string): string {
  return value.slice(0, 10);
}

export function parseTodoDateOnlyAsLocalDate(value: string): Date {
  const [year, month, day] = todoDateOnly(value).split('-').map(Number);
  return new Date(year, (month || 1) - 1, day || 1);
}

export function formatTodoDateOnly(value: string): string {
  return parseTodoDateOnlyAsLocalDate(value).toLocaleDateString();
}

export function localTodayDateOnly(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function isTodoDueDateOverdue(dueAt: string): boolean {
  return todoDateOnly(dueAt) < localTodayDateOnly();
}
