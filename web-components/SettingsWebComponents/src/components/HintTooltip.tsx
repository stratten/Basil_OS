interface HintTooltipProps {
  /** What the explanation is about, such as "Voice Listener". It names the button for assistive technology. */
  subject: string
  /** The explanation shown in the tooltip. */
  text: string
}

/** A circled "?" that explains a switch row on hover or keyboard focus through Basil's shared tooltip (installBasilTooltips), so it matches every other tooltip in the window and the row stays one short line. */
export function HintTooltip({ subject, text }: HintTooltipProps) {
  return (
    <span className="hint-tooltip">
      <button type="button" className="hint-tooltip-trigger" aria-label={`About ${subject}`} data-tooltip={text}>?</button>
    </span>
  )
}
