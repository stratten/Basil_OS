export type DateDisplayStyle = 'relative' | 'absolute'

/** Reads the host's Date & Time preference value; anything other than "absolute" means relative, the default. */
export function normalizeDateDisplayStyle(style: string | undefined | null): DateDisplayStyle {
  return style === 'absolute' ? 'absolute' : 'relative'
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/**
 * Format a timestamp for history display, mirroring the Swift DateFormattingUtils semantics:
 *  - relative: "Today, 10:45 AM" / "Yesterday, 10:45 AM" / "Monday, 10:45 AM" (within the past week) / "Jun 28, 10:45 AM"
 *  - absolute: "2026-06-29 10:45 am" (always shows the year)
 * Both render in the viewer's local time zone.
 */
export function formatTimestampForDisplay(
  input: string | number | Date | undefined | null,
  style: DateDisplayStyle,
): string {
  if (input === undefined || input === null || input === '') return ''
  const date = input instanceof Date ? input : new Date(input)
  if (Number.isNaN(date.getTime())) {
    return typeof input === 'string' ? input : ''
  }

  const pad = (n: number) => String(n).padStart(2, '0')
  const hours12 = date.getHours() % 12 || 12
  const minutes = pad(date.getMinutes())
  const isPM = date.getHours() >= 12

  if (style === 'absolute') {
    const year = date.getFullYear()
    const month = pad(date.getMonth() + 1)
    const day = pad(date.getDate())
    const ampm = isPM ? 'pm' : 'am'
    return `${year}-${month}-${day} ${hours12}:${minutes} ${ampm}`
  }

  // Relative
  const timeStr = `${hours12}:${minutes} ${isPM ? 'PM' : 'AM'}`
  const now = new Date()
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000)

  if (dayDiff === 0) return `Today, ${timeStr}`
  if (dayDiff === 1) return `Yesterday, ${timeStr}`
  if (dayDiff > 1 && dayDiff < 7) {
    const weekday = date.toLocaleDateString(undefined, { weekday: 'long' })
    return `${weekday}, ${timeStr}`
  }
  const monthDay = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  return `${monthDay}, ${timeStr}`
}
