import { useRef, useState } from 'react'

import './context-import-panel.css'

export const MAX_IMPORT_FILE_BYTES = 1024 * 1024

interface Props {
  inputId: string
  placeholder: string
  /** A plain sentence saying where the text goes, shown before anything is sent. */
  routeNotice: string
  startLabel: string
  workingLabel: string
  working: boolean
  text: string
  filename: string
  onChange: (text: string, filename: string) => void
  onStart: () => void
}

/** The text box, file chooser, route notice and start button shared by the records import and the profile import. */
export function ImportSourceInput({ inputId, placeholder, routeNotice, startLabel, workingLabel, working, text, filename, onChange, onStart }: Props) {
  const [fileError, setFileError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const busy = working || opening

  const chooseFile = async (file: File | undefined) => {
    if (!file) return
    setFileError(null)
    if (file.size > MAX_IMPORT_FILE_BYTES) {
      setFileError(`That file is ${(file.size / (1024 * 1024)).toFixed(1)} MB. One import can be up to ${MAX_IMPORT_FILE_BYTES / (1024 * 1024)} MB. Split it and import the parts one at a time.`)
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    setOpening(true)
    try {
      onChange(await file.text(), file.name)
    } catch {
      setFileError('That file could not be read. Try pasting its text instead.')
    } finally {
      setOpening(false)
    }
  }

  return (
    <div className="context-import-input">
      <p className="context-import-route-notice" data-testid="context-import-route-notice">{routeNotice}</p>
      <label className="context-import-label" htmlFor={inputId}>Your text</label>
      <textarea
        id={inputId}
        className="context-import-textarea"
        value={text}
        rows={6}
        disabled={busy}
        onChange={event => onChange(event.target.value, '')}
        placeholder={placeholder}
      />
      <div className="context-import-actions">
        {/* The browser's own file control draws a system button, "No file chosen" text and a file-type icon, none of which match the rest of the app, so the input is hidden and this button opens it. */}
        <button type="button" className="secondary-button context-import-choose" disabled={busy} onClick={() => fileInputRef.current?.click()}>
          Choose a file
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="context-import-file"
          accept=".md,.markdown,.txt,.text,.csv,.json,.jsonl,.log,.html,.htm,.xml,text/plain,text/markdown,text/csv,application/json"
          aria-label="Choose a file to import"
          disabled={busy}
          onChange={event => { void chooseFile(event.target.files?.[0]) }}
        />
        <button type="button" className="primary-button context-import-review" disabled={!text.trim() || busy} onClick={onStart}>
          {working ? workingLabel : opening ? 'Opening file...' : startLabel}
        </button>
      </div>
      {filename && <p className="context-import-hint">Loaded {filename}.</p>}
      {fileError && <p className="context-import-error" role="alert">{fileError}</p>}
    </div>
  )
}
