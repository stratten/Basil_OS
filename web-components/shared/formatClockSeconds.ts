export interface FormatClockSecondsOptions {
  /** Pad the leading unit to two digits ("02:03" instead of "2:03"). Use it only where the label sits beside transcript markers, which are always written as [mm:ss]. */
  padMinutes?: boolean;
}

/**
 * Format a count of seconds as a clock: "m:ss", or "h:mm:ss" once the value reaches an hour.
 * Fractions are floored, negative and non-finite input is treated as zero.
 */
export function formatClockSeconds(seconds: number, options: FormatClockSecondsOptions = {}): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secondsPart = String(total % 60).padStart(2, '0');
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${secondsPart}`;
  }
  const minutesPart = options.padMinutes ? String(minutes).padStart(2, '0') : String(minutes);
  return `${minutesPart}:${secondsPart}`;
}
