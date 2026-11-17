import { useRef, useState } from 'react'

import './context-import-panel.css'
import { MAX_IMPORT_IMAGE_BYTES, MAX_IMPORT_IMAGES, type ImportImagePayload } from './contextImportClient'

export const MAX_IMPORT_FILE_BYTES = 1024 * 1024

/** The screenshot types the backend accepts. */
const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif'

async function imagePayload(file: File): Promise<ImportImagePayload> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(new Error('That picture could not be opened.'))
    reader.readAsDataURL(file)
  })
  const separator = dataUrl.indexOf(',')
  return { mime_type: file.type, data_base64: separator >= 0 ? dataUrl.slice(separator + 1) : '' }
}

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
  /** When given, a "Read a screenshot" button appears. It receives the chosen pictures and returns the text they contain, or throws with a message to show. */
  onReadImages?: (images: ImportImagePayload[]) => Promise<string>
}

/** The text box, file chooser, route notice and start button shared by the records import and the profile import. */
export function ImportSourceInput({ inputId, placeholder, routeNotice, startLabel, workingLabel, working, text, filename, onChange, onStart, onReadImages }: Props) {
  const [fileError, setFileError] = useState<string | null>(null)
  const [opening, setOpening] = useState(false)
  const [readingImages, setReadingImages] = useState(false)
  const [imageNote, setImageNote] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const busy = working || opening || readingImages

  const chooseImages = async (files: File[]) => {
    if (files.length === 0 || !onReadImages) return
    setFileError(null)
    setImageNote(null)
    const resetInput = () => { if (imageInputRef.current) imageInputRef.current.value = '' }
    if (files.length > MAX_IMPORT_IMAGES) {
      setFileError(`Choose at most ${MAX_IMPORT_IMAGES} screenshots at a time.`)
      resetInput()
      return
    }
    const tooLarge = files.find(file => file.size > MAX_IMPORT_IMAGE_BYTES)
    if (tooLarge) {
      setFileError(`${tooLarge.name} is ${(tooLarge.size / 1_000_000).toFixed(1)} MB. A screenshot can be up to ${MAX_IMPORT_IMAGE_BYTES / 1_000_000} MB. Crop it or use a smaller one.`)
      resetInput()
      return
    }
    setReadingImages(true)
    try {
      const payloads = await Promise.all(files.map(imagePayload))
      const read = (await onReadImages(payloads)).trim()
      onChange(text.trim() ? `${text.trim()}\n\n${read}` : read, '')
      setImageNote('I read this from your screenshot. Check it and fix anything I misread, then continue.')
    } catch (error) {
      setFileError(error instanceof Error && error.message ? error.message : 'I could not read that screenshot. Try pasting the text instead.')
    } finally {
      setReadingImages(false)
      resetInput()
    }
  }

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
        {onReadImages && (
          <>
            <button type="button" className="secondary-button context-import-choose" disabled={busy} onClick={() => imageInputRef.current?.click()}>
              {readingImages ? 'Reading screenshot...' : 'Read a screenshot'}
            </button>
            <input
              ref={imageInputRef}
              type="file"
              multiple
              className="context-import-file"
              accept={IMAGE_ACCEPT}
              aria-label="Choose screenshots to read"
              disabled={busy}
              onChange={event => { void chooseImages(Array.from(event.target.files ?? [])) }}
            />
          </>
        )}
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
      {imageNote && <p className="context-import-hint" role="status">{imageNote}</p>}
      {fileError && <p className="context-import-error" role="alert">{fileError}</p>}
    </div>
  )
}
