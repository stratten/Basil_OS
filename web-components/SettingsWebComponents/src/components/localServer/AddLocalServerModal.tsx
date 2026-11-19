import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { requestRegisterLocalServer } from '../../services/connections/connectionsBridge'
import {
  EMPTY_LOCAL_SERVER_FORM,
  buildLocalServerRegistration,
  namesMissingValues,
  secretNamesInForm,
  secretValuesFor,
  type LocalServerFormValues,
} from './localServerForm'
import { SettingsModalCard } from '../modal/SettingsModalCard'

interface AddLocalServerModalProps {
  pendingId: string | null
  requestError?: string | null
  onTrackRequest: (id: string) => void
  onBack: () => void
  onDismiss: () => void
}

type TextKey = { [K in keyof LocalServerFormValues]: LocalServerFormValues[K] extends string ? K : never }[keyof LocalServerFormValues]

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="connections-add-form-field">
      {label}
      {children}
      {hint && <span className="connections-local-hint">{hint}</span>}
    </label>
  )
}

export function AddLocalServerModal({ pendingId, requestError = null, onTrackRequest, onBack, onDismiss }: AddLocalServerModalProps) {
  const [form, setForm] = useState<LocalServerFormValues>(EMPTY_LOCAL_SERVER_FORM)
  const [secretValues, setSecretValues] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [trackedRequestId, setTrackedRequestId] = useState<string | null>(null)
  const disabled = pendingId !== null
  const isAdding = trackedRequestId !== null && pendingId === trackedRequestId
  const secretNames = secretNamesInForm(form)

  // The request is finished once the parent, having shown it as pending, clears its pending id. Waiting to see it pending first means a parent that lags a render behind cannot make the form think the request already finished. The form closes only when the request finished without an error, so a failed attempt never loses what was typed.
  const sawRequestPending = useRef(false)
  useEffect(() => {
    if (!trackedRequestId) return
    if (pendingId === trackedRequestId) {
      sawRequestPending.current = true
      return
    }
    if (!sawRequestPending.current) return
    sawRequestPending.current = false
    setTrackedRequestId(null)
    if (!requestError) onDismiss()
  }, [pendingId, trackedRequestId, requestError, onDismiss])

  function setField<K extends keyof LocalServerFormValues>(key: K, value: LocalServerFormValues[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function text(key: TextKey) {
    return {
      name: key,
      value: form[key],
      disabled,
      onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setField(key, event.target.value),
    }
  }

  function submit() {
    const built = buildLocalServerRegistration(form)
    if (!built.ok) {
      setFormError(built.error)
      return
    }
    const missing = namesMissingValues(secretNames, secretValues)
    if (missing.length > 0) {
      setFormError(`Enter a value for ${missing.join(', ')}.`)
      return
    }
    setFormError(null)
    const id = requestRegisterLocalServer(built.value, secretValuesFor(secretNames, secretValues))
    sawRequestPending.current = false
    onTrackRequest(id)
    setTrackedRequestId(id)
  }

  const shownError = formError ?? (isAdding ? null : requestError)

  return (
    <SettingsModalCard
      title="Add a local server"
      subtitle="A program on this Mac that speaks MCP. Basil starts it when it is needed."
      className="connections-local-modal"
      onClose={onDismiss}
      closeDisabled={disabled}
    >
      <p className="connections-local-warning" role="note">
        This runs a program with your account&apos;s full access to your files and network. Only add programs you trust.
      </p>

      <Field label="Name">
        <input type="text" placeholder="e.g. WhatsApp" {...text('name')} />
      </Field>
      <Field label="Description (optional)">
        <input type="text" placeholder="What will this server be used for?" {...text('description')} />
      </Field>
      <Field label="Command">
        <input type="text" placeholder="/usr/local/bin/uv" spellCheck={false} autoComplete="off" {...text('command')} />
      </Field>
      <Field label="Arguments" hint="One argument per line. An argument that contains spaces stays on one line.">
        <textarea rows={3} spellCheck={false} {...text('argsText')} name="args" />
      </Field>
      <Field label="Folder (optional)" hint="The absolute path the program runs in.">
        <input type="text" placeholder="/Users/you/projects/server" spellCheck={false} autoComplete="off" {...text('folder')} />
      </Field>
      <Field label="Settings (optional)" hint="One NAME=value per line. Do not put passwords or keys here; list them under Secrets.">
        <textarea rows={3} spellCheck={false} {...text('envText')} name="env" />
      </Field>
      <Field label="Secrets (optional)" hint="Names only, such as API_KEY. You type each value below, and Basil keeps it in your Keychain.">
        <input type="text" placeholder="API_KEY, ACCESS_TOKEN" spellCheck={false} autoComplete="off" {...text('secretNamesText')} name="secretNames" />
      </Field>
      <Field label="Where the instructions came from (optional)">
        <input type="text" placeholder="https://github.com/..." spellCheck={false} autoComplete="off" {...text('sourceUrl')} />
      </Field>

      <details className="connections-local-recipe">
        <summary>Paste a setup recipe (optional)</summary>
        <Field label="Setup recipe" hint="JSON with an &quot;install&quot; part listing the programs to install and the files to download or build, and a &quot;probe&quot; part naming the program's status page. Basil shows every address, hash and command for your approval before anything runs.">
          <textarea rows={6} spellCheck={false} {...text('recipeText')} name="recipe" />
        </Field>
      </details>

      <label className="connections-local-check">
        <input type="checkbox" name="useCompanion" checked={form.useCompanion} disabled={disabled} onChange={(event) => setField('useCompanion', event.target.checked)} />
        This server needs a background program running first
      </label>

      {form.useCompanion && (
        <div className="connections-local-section">
          <h4 className="connections-add-modal-section-title">Background program</h4>
          <p className="connections-local-hint">
            Write {'{port}'} in this program&apos;s arguments or settings, and in the server&apos;s, and Basil fills in a free port each time.
          </p>
          <Field label="Command">
            <input type="text" placeholder="/usr/local/bin/go" spellCheck={false} autoComplete="off" {...text('companionCommand')} />
          </Field>
          <Field label="Arguments" hint="One argument per line.">
            <textarea rows={3} spellCheck={false} {...text('companionArgsText')} name="companionArgs" />
          </Field>
          <Field label="Folder (optional)">
            <input type="text" spellCheck={false} autoComplete="off" {...text('companionFolder')} />
          </Field>
          <Field label="Settings (optional)" hint="One NAME=value per line.">
            <textarea rows={2} spellCheck={false} {...text('companionEnvText')} name="companionEnv" />
          </Field>
          <Field label="Secrets (optional)" hint="Names only. A name the server also uses is entered once.">
            <input type="text" spellCheck={false} autoComplete="off" {...text('companionSecretNamesText')} name="companionSecretNames" />
          </Field>
          <Field label="Fixed port (optional)" hint="Only when the program insists on one port. Leave empty to let Basil choose.">
            <input type="text" inputMode="numeric" placeholder="e.g. 8080" {...text('fixedPortText')} name="fixedPort" />
          </Field>
          <label className="connections-local-check">
            <input type="checkbox" name="startWithBasil" checked={form.startWithBasil} disabled={disabled} onChange={(event) => setField('startWithBasil', event.target.checked)} />
            Start it whenever Basil starts
          </label>
        </div>
      )}

      {secretNames.length > 0 && (
        <div className="connections-local-section">
          <h4 className="connections-add-modal-section-title">Secret values</h4>
          {secretNames.map((secretName) => (
            <Field key={secretName} label={`Value for ${secretName}`}>
              <input
                type="password"
                name={`secret-${secretName}`}
                autoComplete="off"
                value={secretValues[secretName] ?? ''}
                disabled={disabled}
                onChange={(event) => setSecretValues((current) => ({ ...current, [secretName]: event.target.value }))}
              />
            </Field>
          ))}
        </div>
      )}

      {shownError && <p className="connections-local-error" role="alert">{shownError}</p>}
      {isAdding && (
        <p className="connections-local-progress" role="status">
          Adding and starting the server. A program that has to be built first can take up to a minute.
        </p>
      )}

      <div className="connections-add-form-actions">
        <button type="button" className="secondary-button" disabled={disabled} onClick={onBack}>Back</button>
        <button type="button" className="primary-button" disabled={disabled} onClick={submit}>Add and start</button>
      </div>
    </SettingsModalCard>
  )
}
