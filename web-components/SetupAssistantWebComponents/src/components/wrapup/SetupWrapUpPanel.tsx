import { useState } from 'react'

import { plainMarkdownText } from '@shared/plainMarkdownText'
import { SetupConversationMarkdown } from '@/components/conversation/SetupConversationMarkdown'
import { SetupWorkingIndicator } from '@/components/motion/SetupWorkingIndicator'
import type { SetupWrapUpProposal } from '@/types'

import {
  copyWrapUpReferenceMarkdown,
  downloadWrapUpReferencePdf,
} from './wrapUpReferenceExport'

// Terminal-screen wrap-up panel. Renders one of four UI variants depending
// on how the user reached the wrap-up stage and how the finalize call
// resolved:
//   - wasSkipped: user clicked Skip in the shell header
//   - wrapUpProposal present + recap non-empty: model produced a recap
//   - isFinalizingWrapUp: the finalize stream is still in flight
//   - finalizeError: finalize stream failed
//   - (fallback) nothing happened to land any setup steps this round
//
// All four variants share the same `<SettingsPointer>` footer so the
// "Settings > General > Application Setup" copy is identical wherever
// the user lands.

export interface SetupWrapUpPanelProps {
  wasSkipped: boolean
  wrapUpProposal?: SetupWrapUpProposal
  isFinalizingWrapUp: boolean
  finalizeError: string | null
}

function SettingsPointer() {
  return (
    <p className="setup-wrapup-settings-pointer">
      You can launch the Setup Assistant again any time from
      {' '}<strong>Settings &rsaquo; General &rsaquo; Application Setup</strong>.
    </p>
  )
}

export function SetupWrapUpPanel({
  wasSkipped,
  wrapUpProposal,
  isFinalizingWrapUp,
  finalizeError,
}: SetupWrapUpPanelProps) {
  const [exportStatus, setExportStatus] = useState<string | null>(null)

  const handleDownloadPdf = (proposal: SetupWrapUpProposal) => {
    setExportStatus('Preparing your PDF...')
    downloadWrapUpReferencePdf(proposal)
      .then(message => setExportStatus(message))
      .catch(error => setExportStatus(error instanceof Error ? error.message : String(error)))
  }

  const handleCopyMarkdown = (proposal: SetupWrapUpProposal) => {
    copyWrapUpReferenceMarkdown(proposal)
      .then(() => setExportStatus('Markdown copied.'))
      .catch(error => setExportStatus(error instanceof Error ? error.message : String(error)))
  }

  if (wasSkipped) {
    return (
      <section key="skipped" className="setup-complete-panel setup-motion-enter">
        <p className="setup-complete-eyebrow">Saved for later</p>
        <h1>I saved your spot.</h1>
        <p>
          No pressure. I'll bring this back up the next time you launch the app, and you can
          resume from Settings any time.
        </p>
        <SettingsPointer />
      </section>
    )
  }

  if (wrapUpProposal && wrapUpProposal.recap.trim().length > 0) {
    return (
      <section key="ready" className="setup-complete-panel setup-complete-panel--agent setup-motion-enter">
        <p className="setup-complete-eyebrow">Here's where we landed</p>
        <h1>I'm ready to help.</h1>
        <div className="setup-wrapup-recap">
          <SetupConversationMarkdown content={wrapUpProposal.recap} />
        </div>

        {wrapUpProposal.recommended_next_steps.length > 0 && (
          <div className="setup-wrapup-next-steps">
            <h2>Recommended next steps</h2>
            <ul>
              {wrapUpProposal.recommended_next_steps.map(step => (
                <li key={step.id}>
                  <strong>{plainMarkdownText(step.label)}</strong>
                  <span>{plainMarkdownText(step.message)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {wrapUpProposal.optional_breadth && wrapUpProposal.optional_breadth.trim().length > 0 && (
          <div className="setup-wrapup-breadth">
            <h2>You can come back to</h2>
            <SetupConversationMarkdown content={wrapUpProposal.optional_breadth} />
          </div>
        )}

        <div className="setup-wrapup-export-actions">
          <button
            type="button"
            className="primary-button"
            onClick={() => handleDownloadPdf(wrapUpProposal)}
          >
            Download PDF
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => handleCopyMarkdown(wrapUpProposal)}
          >
            Copy Markdown
          </button>
          {exportStatus && (
            <p className="setup-wrapup-export-status" role="status">{exportStatus}</p>
          )}
        </div>

        <SettingsPointer />
      </section>
    )
  }

  if (isFinalizingWrapUp) {
    return (
      <section key="preparing" className="setup-complete-panel setup-wrapup--preparing setup-motion-enter">
        <p className="setup-complete-eyebrow">Wrapping up</p>
        <h1>Putting your recap together&hellip;</h1>
        <p>
          I'm doing a careful read of what we covered and what's worth flagging next — it'll
          be ready in a moment. (You can always resume this from
          {' '}<strong>Settings &rsaquo; General &rsaquo; Application Setup</strong>
          {' '}later.)
        </p>
        <SetupWorkingIndicator className="setup-wrapup-working" label="Reading back through what we covered." />
      </section>
    )
  }

  if (finalizeError) {
    return (
      <section key="error" className="setup-complete-panel setup-motion-enter">
        <p className="setup-complete-eyebrow">Wrapped up</p>
        <h1>I couldn't pull a recap together — but I'm ready when you are.</h1>
        <p>
          Something got in the way when I tried to summarize what we landed on. You can resume
          the Setup Assistant any time and pick this back up.
        </p>
        <SettingsPointer />
      </section>
    )
  }

  return (
    <section key="fallback" className="setup-complete-panel setup-motion-enter">
      <p className="setup-complete-eyebrow">All set for now</p>
      <h1>I'm ready when you are.</h1>
      <p>
        We didn't land any concrete setup steps this round, but that's fine — you can come back
        to this any time, and I'll only act on things you approve.
      </p>
      <SettingsPointer />
    </section>
  )
}
