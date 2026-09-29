interface SetupWorkingIndicatorProps {
  label: string
  detail?: string | null
  quiet?: boolean
  className?: string
}

// Shared "Basil is working" line for orientation, the conversation, and wrap-up. The label is keyed so a changed narration fades in instead of snapping.
export function SetupWorkingIndicator({ label, detail, quiet = false, className }: SetupWorkingIndicatorProps) {
  const classes = ['setup-working-indicator', className].filter(Boolean).join(' ')
  const labelClassName = quiet ? 'setup-working-text setup-working-substatus' : 'setup-working-text'
  return (
    <div className={classes} role="status" aria-live="polite">
      <span className="setup-working-dot" aria-hidden="true" />
      <div>
        <p key={label} className={labelClassName}>{label}</p>
        {detail && <p className="setup-working-substatus">{detail}</p>}
      </div>
    </div>
  )
}
