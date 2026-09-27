export function generateModelId(displayName: string): string {
  return displayName
    .toLowerCase()
    .replace(/ /g, '-')
    .replace(/_/g, '-')
    .split('')
    .filter((char) => /[a-z0-9\-.]/.test(char))
    .join('')
}
