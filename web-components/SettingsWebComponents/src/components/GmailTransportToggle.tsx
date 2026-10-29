import type { GmailTransport } from '../types'
import { PolicyRadioGroup, type PolicyRadioOption } from './PolicyRadioGroup'

const TRANSPORT_OPTIONS: readonly PolicyRadioOption<GmailTransport>[] = [
  {
    id: 'direct',
    label: 'Direct (Gmail API)',
    description: 'Basil calls the Gmail API directly. This works for any Google Cloud project that has the Gmail API turned on.',
  },
  {
    id: 'mcp',
    label: "Hosted (Google's Gmail MCP server)",
    description: "Basil calls Google's hosted Gmail MCP server. This only works for Google Cloud projects enrolled in Google's Developer Preview Program.",
  },
]

export function gmailTransportSummary(transport: GmailTransport, pinnedByEnvironment: boolean): string {
  const base = transport === 'mcp' ? "Connects through Google's hosted Gmail server." : 'Connects through the Gmail API.'
  return pinnedByEnvironment ? `${base} Set by the BASIL_GMAIL_TRANSPORT environment variable.` : base
}

interface GmailTransportToggleProps {
  value: GmailTransport
  pinnedByEnvironment: boolean
  disabled: boolean
  onChange: (next: GmailTransport) => void
}

/** A controlled chooser; the caller decides when the choice is saved. */
export function GmailTransportToggle({ value, pinnedByEnvironment, disabled, onChange }: GmailTransportToggleProps) {
  return (
    <div className="connections-gmail-transport">
      <PolicyRadioGroup
        legend="Gmail connection mechanism"
        name="gmail-transport"
        options={TRANSPORT_OPTIONS}
        value={value}
        disabled={disabled || pinnedByEnvironment}
        onChange={onChange}
      />
      <p className="connections-add-form-hint">
        Both use the same Google sign-in, so switching never asks you to sign in again.
        {pinnedByEnvironment && ' The BASIL_GMAIL_TRANSPORT environment variable is set, so it decides this and the choice above cannot be changed here.'}
      </p>
    </div>
  )
}
