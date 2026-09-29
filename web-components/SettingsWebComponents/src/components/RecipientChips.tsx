import { useState } from 'react'

export function parseRecipients(value: string | null | undefined): string[] {
  return (value ?? '').split(/[,;]/).map((token) => token.trim()).filter(Boolean)
}

function mergeRecipients(existing: string[], additions: string[]): string[] {
  const seen = new Set(existing.map((token) => token.toLocaleLowerCase()))
  const merged = [...existing]
  for (const addition of additions) {
    const key = addition.toLocaleLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(addition)
  }
  return merged
}

export function RecipientChipList({ recipient }: { recipient: string }) {
  const tokens = parseRecipients(recipient)
  if (tokens.length === 0) return null
  return (
    <div className="writing-examples-list-recipient">
      <span className="writing-examples-recipient-label">To:</span>
      <ul className="writing-examples-recipient-chips" aria-label="Recipients">
        {tokens.map((token, index) => (
          <li key={`${token}-${index}`} className="writing-examples-recipient-chip">{token}</li>
        ))}
      </ul>
    </div>
  )
}

/** Comma-separated recipient entry, matching the meeting participant field; the stored value stays a ", "-joined string. */
export function RecipientChipsInput({
  id,
  value,
  onChange,
  disabled = false,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const [draft, setDraft] = useState('')
  const tokens = parseRecipients(value)

  function commit(text: string, remainder = '') {
    const additions = parseRecipients(text)
    if (additions.length > 0) onChange(mergeRecipients(tokens, additions).join(', '))
    setDraft(remainder)
  }

  function remove(index: number) {
    onChange(tokens.filter((_, tokenIndex) => tokenIndex !== index).join(', '))
  }

  return (
    <div className="writing-examples-recipient-field">
      {tokens.map((token, index) => (
        <span key={`${token}-${index}`} className="writing-examples-recipient-chip">
          <span>{token}</span>
          <button type="button" aria-label={`Remove ${token}`} disabled={disabled} onClick={() => remove(index)}>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="8" cy="8" r="6" />
              <path d="m5.8 5.8 4.4 4.4m0-4.4-4.4 4.4" fill="none" stroke="white" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </button>
        </span>
      ))}
      <input
        id={id}
        type="text"
        className="writing-examples-recipient-draft"
        value={draft}
        disabled={disabled}
        placeholder={tokens.length === 0 ? 'Recipients (comma separated)' : 'Add recipient'}
        onChange={(event) => {
          const next = event.target.value
          const lastSeparator = Math.max(next.lastIndexOf(','), next.lastIndexOf(';'))
          if (lastSeparator >= 0) {
            commit(next.slice(0, lastSeparator), next.slice(lastSeparator + 1).trimStart())
          } else {
            setDraft(next)
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            commit(draft)
          } else if (event.key === 'Backspace' && draft === '' && tokens.length > 0) {
            event.preventDefault()
            remove(tokens.length - 1)
          }
        }}
        onBlur={() => commit(draft)}
      />
    </div>
  )
}
