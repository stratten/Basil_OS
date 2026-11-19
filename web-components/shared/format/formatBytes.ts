/** Writes a byte count in decimal units, such as "400 bytes", "1.0 KB" or "5.7 GB", the way the download progress displays show it. */
export function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 bytes'
  const units = ['bytes', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unitIndex = 0
  while (value >= 1000 && unitIndex < units.length - 1) {
    value /= 1000
    unitIndex += 1
  }
  const precision = unitIndex === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(precision)} ${units[unitIndex]}`
}
