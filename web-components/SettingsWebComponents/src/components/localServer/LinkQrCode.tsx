import { useMemo } from 'react'
import qrcode from 'qrcode-generator'

interface LinkQrCodeProps {
  /** The text the code carries. It is drawn here and never sent anywhere else. */
  value: string
  /** What a person scanning is told the code is for, for assistive technology. */
  label: string
}

/** One SVG path that fills every dark module of the code, or null when the text cannot be encoded. */
export function qrPath(value: string): { path: string; size: number } | null {
  if (!value) return null
  try {
    const code = qrcode(0, 'M')
    code.addData(value)
    code.make()
    const count = code.getModuleCount()
    let path = ''
    for (let row = 0; row < count; row += 1) {
      for (let column = 0; column < count; column += 1) {
        if (code.isDark(row, column)) path += `M${column} ${row}h1v1h-1z`
      }
    }
    return { path, size: count }
  } catch {
    return null
  }
}

/** A scannable code, always black on white with a quiet zone so a phone camera reads it in either theme. */
export function LinkQrCode({ value, label }: LinkQrCodeProps) {
  const drawn = useMemo(() => qrPath(value), [value])
  if (!drawn) {
    return <p className="connections-local-error" role="alert">The code could not be drawn. A new one appears here when the program makes it.</p>
  }
  const quiet = 4
  const total = drawn.size + quiet * 2
  return (
    <svg
      className="connections-local-qr"
      role="img"
      aria-label={label}
      viewBox={`0 0 ${total} ${total}`}
      shapeRendering="crispEdges"
    >
      <rect width={total} height={total} fill="#ffffff" />
      <path transform={`translate(${quiet} ${quiet})`} d={drawn.path} fill="#000000" />
    </svg>
  )
}
