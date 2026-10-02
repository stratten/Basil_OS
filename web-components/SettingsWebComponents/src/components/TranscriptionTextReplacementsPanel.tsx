import { useState } from 'react'
import { requestUpdateTextReplacements } from '../services/transcriptionSettingsBridge'
import type { TranscriptionTextReplacementFields } from '../types'

const TEXT_REPLACEMENT_SOURCE_MAX_LENGTH = 120
const TEXT_REPLACEMENT_REPLACEMENT_MAX_LENGTH = 500

interface TranscriptionTextReplacementsPanelProps {
  rules: TranscriptionTextReplacementFields[]
  disabled?: boolean
  onRulesChange: (rules: TranscriptionTextReplacementFields[]) => void
  onTrackRequest: (id: string) => void
}

export function TranscriptionTextReplacementsPanel({ rules, disabled, onRulesChange, onTrackRequest }: TranscriptionTextReplacementsPanelProps) {
  const [sourceDraft, setSourceDraft] = useState('')
  const [replacementDraft, setReplacementDraft] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  function submitRules(next: TranscriptionTextReplacementFields[]) {
    onRulesChange(next)
    onTrackRequest(requestUpdateTextReplacements(next))
  }

  function addRule() {
    const source = sourceDraft.trim().replace(/\s+/g, ' ')
    const replacement = replacementDraft
    if (!source) {
      setFormError('Enter the spoken phrase to match.')
      return
    }
    if (source.length > TEXT_REPLACEMENT_SOURCE_MAX_LENGTH) {
      setFormError(`Spoken phrase cannot exceed ${TEXT_REPLACEMENT_SOURCE_MAX_LENGTH} characters.`)
      return
    }
    if (replacement.length > TEXT_REPLACEMENT_REPLACEMENT_MAX_LENGTH) {
      setFormError(`Replacement cannot exceed ${TEXT_REPLACEMENT_REPLACEMENT_MAX_LENGTH} characters.`)
      return
    }
    if (rules.some((rule) => rule.source.toLowerCase() === source.toLowerCase())) {
      setFormError('A rule for this phrase already exists.')
      return
    }

    submitRules([...rules, { source, replacement }])
    setSourceDraft('')
    setReplacementDraft('')
    setFormError(null)
  }

  function removeRule(index: number) {
    submitRules(rules.filter((_, ruleIndex) => ruleIndex !== index))
  }

  return (
    <div className="transcription-settings-panel">
      <section className="transcription-settings-section">
        <h2>Text replacements</h2>
        <p className="transcription-settings-hint">Replace a spoken phrase with exact text when Basil copies or pastes a transcription. This never changes the transcript shown in Basil.</p>
        <div className="transcription-text-replacement-form">
          <div className="transcription-text-replacement-field">
            <label htmlFor="transcription-replacement-source">Spoken phrase</label>
            <input
              id="transcription-replacement-source"
              type="text"
              placeholder="e.g. slash"
              maxLength={TEXT_REPLACEMENT_SOURCE_MAX_LENGTH}
              value={sourceDraft}
              disabled={disabled}
              onChange={(event) => setSourceDraft(event.target.value)}
            />
          </div>
          <div className="transcription-text-replacement-field">
            <label htmlFor="transcription-replacement-target">Replace with</label>
            <input
              id="transcription-replacement-target"
              type="text"
              placeholder="e.g. /"
              maxLength={TEXT_REPLACEMENT_REPLACEMENT_MAX_LENGTH}
              value={replacementDraft}
              disabled={disabled}
              onChange={(event) => setReplacementDraft(event.target.value)}
            />
          </div>
          <button
            type="button"
            className="secondary-button transcription-text-replacement-add"
            disabled={disabled}
            onClick={addRule}
          >
            Add
          </button>
        </div>
        {formError && <p className="transcription-settings-error" role="alert">{formError}</p>}
        <h3>Configured replacements</h3>
        {rules.length === 0 ? (
          <p className="transcription-settings-hint">No replacements added yet. Rules you add above will appear here.</p>
        ) : (
          <ul className="transcription-text-replacement-list">
            {rules.map((rule, index) => (
              <li key={`${rule.source}-${index}`} className="transcription-text-replacement-row">
                <span className="transcription-text-replacement-source">{rule.source}</span>
                <span className="transcription-text-replacement-arrow" aria-hidden="true">→</span>
                <span className="transcription-text-replacement-target">{rule.replacement || '(empty)'}</span>
                <button
                  type="button"
                  className="secondary-button transcription-text-replacement-remove"
                  disabled={disabled}
                  aria-label={`Remove replacement for ${rule.source}`}
                  onClick={() => removeRule(index)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
