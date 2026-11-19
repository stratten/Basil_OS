import { useEffect, useState } from 'react'

import './context-import-panel.css'
import { BasilModalDialog } from '../dialogs/BasilModalDialog'
import type { ContextImportClient, ImportModelAccess, ProfileCommitResult, ProfileDraft } from './contextImportClient'
import { ImportJobProgress } from './ImportJobProgress'
import { ImportSourceInput } from './ImportSourceInput'
import { useContextImportJob } from './useContextImportJob'

type Stage = 'input' | 'review' | 'saving' | 'done'

/** The working and review dialogs end only through their own buttons, so Escape and a backdrop click do nothing. */
const keepOpen = () => {}

export interface ProfileImportOutcome {
  /** One sentence from the model saying what the saved profile covers. */
  summary: string
  filesUpdated: string[]
  backupId: string | null
}

interface Props {
  client: ContextImportClient
  /** One plain sentence saying where the text goes, shown above the text box. */
  routeNotice: string
  /** The route confirmed on the setup model step. Leave it out in Settings, where the memory model reads the text. */
  modelAccess?: ImportModelAccess | null
  onImported?: (outcome: ProfileImportOutcome) => void
  /** Called after Undo has put the profile files back, so a caller that recorded the import can forget it. */
  onUndone?: () => void
}

const FILE_COPY: Record<string, { title: string; blurb: string }> = {
  'essentials.md': { title: 'Essentials', blurb: 'The short list of things Basil should always know about you.' },
  'user.md': { title: 'About you', blurb: 'Basil\u2019s longer profile of you: your work, your habits and your preferences.' },
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).length
}

/** Reads text into a rewrite of the person's profile, shows it beside what is there now, and saves only what they approve, with an Undo. */
export function ProfileImportPanel({ client, routeNotice, modelAccess = null, onImported, onUndone }: Props) {
  const [stage, setStage] = useState<Stage>('input')
  const [text, setText] = useState('')
  const [filename, setFilename] = useState('')
  const [draft, setDraft] = useState<ProfileDraft | null>(null)
  const [edited, setEdited] = useState<Record<string, string>>({})
  const [replacing, setReplacing] = useState<Record<string, boolean>>({})
  const [saved, setSaved] = useState<ProfileCommitResult | null>(null)
  const [undone, setUndone] = useState(false)
  const [undoing, setUndoing] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const { view, start, cancel, reset: resetJob } = useContextImportJob<ProfileDraft>(client)

  const working = view.phase === 'starting' || view.phase === 'running'

  useEffect(() => {
    if (view.phase !== 'done' || !view.result) return
    const next = view.result
    setDraft(next)
    setEdited(Object.fromEntries(next.files.map(file => [file.name, file.proposed])))
    setReplacing(Object.fromEntries(next.files.map(file => [file.name, file.proposed.trim() !== file.current.trim()])))
    setStage('review')
    resetJob()
  }, [view, resetJob])

  const begin = () => {
    if (!text.trim() || working) return
    setErrorMessage(null)
    void start(() => client.startProfileJob(text, filename, filename, modelAccess))
  }

  const checkedFiles = draft ? draft.files.filter(file => replacing[file.name]) : []
  const overLimit = checkedFiles.some(file => byteLength(edited[file.name] ?? '') > file.cap_bytes)
  const blankChecked = checkedFiles.some(file => !(edited[file.name] ?? '').trim())
  const canSave = stage === 'review' && checkedFiles.length > 0 && !overLimit && !blankChecked

  const save = async () => {
    if (!draft || !canSave) return
    setErrorMessage(null)
    setStage('saving')
    const textFor = (name: string) => (replacing[name] ? edited[name] ?? '' : '')
    try {
      const result = await client.commitProfile(draft.draft_id, textFor('essentials.md'), textFor('user.md'))
      setSaved(result)
      setStage('done')
      onImported?.({ summary: draft.summary, filesUpdated: result.files_updated, backupId: result.backup_id })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'The profile could not be saved.')
      setStage('review')
    }
  }

  const undo = async () => {
    if (!saved?.backup_id || undoing) return
    setUndoing(true)
    setErrorMessage(null)
    try {
      await client.undoProfile(saved.backup_id)
      setUndone(true)
      onUndone?.()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'The profile could not be restored.')
    } finally {
      setUndoing(false)
    }
  }

  const reset = () => {
    resetJob()
    setText('')
    setFilename('')
    setDraft(null)
    setSaved(null)
    setUndone(false)
    setErrorMessage(null)
    setStage('input')
  }

  const jobProblem = view.phase === 'failed' ? view.error : null
  const canceledNote = view.phase === 'canceled' ? view.message : null
  // While the review dialog is open it shows its own save error, so the page behind it shows only a failed read.
  const pageError = (stage === 'review' || stage === 'saving' ? null : errorMessage) ?? jobProblem

  return (
    <div className="context-import" data-testid="profile-import">
      <h3 className="context-import-title">Build your profile from what you already have</h3>
      <p className="context-import-hint">Choose an export from another app, notes about yourself, or a profile written in Markdown. A model reads it and drafts an update to your profile. You see it beside what is there now, and nothing is saved until you approve it.</p>

      {stage === 'input' && (
        <>
          <ImportSourceInput
            inputId="profile-import-text"
            placeholder={'For example, paste a profile you wrote, or the memory export from another assistant.'}
            routeNotice={routeNotice}
            startLabel="Draft my profile"
            workingLabel="Reading..."
            working={working}
            text={text}
            filename={filename}
            onChange={(nextText, nextFilename) => { setText(nextText); setFilename(nextFilename) }}
            onStart={begin}
            onReadImages={async images => (await client.readImages(images, modelAccess)).text}
          />
          {canceledNote && <p className="context-import-hint" role="status">{canceledNote}</p>}
        </>
      )}

      {working && (
        <BasilModalDialog title="Drafting your profile" onClose={keepOpen} dismissible={false} closeAction={{ onClick: () => { void cancel() } }} testId="profile-import-working">
          <ImportJobProgress
            kind="profile"
            phase={view.phase === 'starting' ? 'starting' : 'running'}
            message={view.message}
            done={view.done}
            total={view.total}
            stage={view.stage}
            tokensWritten={view.tokensWritten}
            thinking={view.thinking}
            onCancel={() => { void cancel() }}
          />
        </BasilModalDialog>
      )}

      {(stage === 'review' || stage === 'saving') && draft && (
        <BasilModalDialog title="Review your profile draft" onClose={keepOpen} dismissible={false} closeAction={{ onClick: reset, disabled: stage === 'saving' }} size="wide" testId="profile-import-review-modal">
        <div className="context-import-review-panel" data-testid="profile-import-review">
          <p className="context-import-summary">{draft.summary || 'Here is the draft of your profile.'}</p>
          {draft.warnings.length > 0 && (
            <ul className="context-import-warnings" role="status">
              {draft.warnings.map(warning => <li key={warning}>{warning}</li>)}
            </ul>
          )}
          {draft.files.map(file => {
            const copy = FILE_COPY[file.name] ?? { title: file.name, blurb: '' }
            const value = edited[file.name] ?? ''
            const size = byteLength(value)
            const unchanged = file.proposed.trim() === file.current.trim()
            return (
              <div key={file.name} className="context-import-category" data-testid={`profile-file-${file.name}`}>
                <label className="context-import-category-label">
                  <input
                    type="checkbox"
                    checked={Boolean(replacing[file.name])}
                    disabled={stage === 'saving'}
                    onChange={event => setReplacing(current => ({ ...current, [file.name]: event.target.checked }))}
                  />
                  <span>{copy.title}{unchanged ? ', no change suggested' : ''}</span>
                </label>
                <p className="context-import-hint">{copy.blurb}</p>
                <div className="context-import-profile-columns">
                  <div>
                    <p className="context-import-label">Now</p>
                    <pre className="context-import-pre" data-testid={`profile-current-${file.name}`}>{file.current.trim() || 'Nothing yet.'}</pre>
                  </div>
                  <div>
                    <label className="context-import-label" htmlFor={`profile-edit-${file.name}`}>After, which you can edit</label>
                    <textarea
                      id={`profile-edit-${file.name}`}
                      className="context-import-textarea"
                      rows={8}
                      value={value}
                      disabled={stage === 'saving'}
                      onChange={event => setEdited(current => ({ ...current, [file.name]: event.target.value }))}
                    />
                    <p className={size > file.cap_bytes ? 'context-import-bytes context-import-bytes--over' : 'context-import-bytes'} data-testid={`profile-bytes-${file.name}`}>
                      {size} of {file.cap_bytes} bytes{size > file.cap_bytes ? '. Shorten it to save.' : ''}
                    </p>
                  </div>
                </div>
              </div>
            )
          })}
          <div className="context-import-actions">
            <button type="button" className="secondary-button" disabled={stage === 'saving'} onClick={reset}>Cancel</button>
            <button type="button" className="primary-button context-import-approve" disabled={!canSave} onClick={() => { void save() }}>
              {stage === 'saving' ? 'Saving...' : 'Save to my profile'}
            </button>
          </div>
          {errorMessage && <p className="context-import-error" role="alert">{errorMessage}</p>}
        </div>
        </BasilModalDialog>
      )}

      {stage === 'done' && saved && (
        <div className="context-import-done" role="status" data-testid="profile-import-done">
          <p className="context-import-summary">
            {undone
              ? 'Your profile is back the way it was.'
              : saved.files_updated.length > 0
                ? `Saved. Updated ${saved.files_updated.map(name => FILE_COPY[name]?.title ?? name).join(' and ')}.`
                : 'Nothing changed, so nothing was saved.'}
          </p>
          <div className="context-import-actions">
            <button type="button" className="secondary-button" onClick={reset}>Import something else</button>
            {saved.backup_id && !undone && (
              <button type="button" className="secondary-button" disabled={undoing} onClick={() => { void undo() }}>
                {undoing ? 'Restoring...' : 'Undo this change'}
              </button>
            )}
          </div>
        </div>
      )}

      {pageError && <p className="context-import-error" role="alert">{pageError}</p>}
    </div>
  )
}
