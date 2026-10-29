import { useEffect, useRef, useState } from 'react';
import { ThumbDownIcon, ThumbUpIcon } from '../components/MeetingIcons';
import CompanionActionButtons from './CompanionActionButtons';
import { formatClockSeconds } from '@shared/formatClockSeconds';
import { AUDIT_KIND_LABELS, auditButtonLabel, auditCounterText, momentAsItem } from './companionAuditView';
import { linkedActionText } from './CompanionItemCard';
import { useCompanionLinks } from './companionLinks';
import type { CompanionAudit, CompanionAuditMoment, CompanionFeedbackAction, CompanionItem, CompanionItemAction, CompanionItemActionResult } from './types';

interface CompanionAuditSectionProps {
  audit: CompanionAudit | null;
  auditing: boolean;
  isRecording: boolean;
  /** The message of the latest audit_failed error, when there was one. */
  failureMessage: string | null;
  researchOn: boolean;
  allowedActions: readonly CompanionItemAction[];
  /** The action card made from each finding or note, keyed by the id of what it came from. */
  actionCards: ReadonlyMap<string, CompanionItem>;
  onRun: () => Promise<boolean>;
  onInvestigate: (question: string) => void;
  onAction: (itemId: string, action: CompanionItemAction) => Promise<CompanionItemActionResult | null>;
  onMark: (momentId: string, action: CompanionFeedbackAction) => Promise<boolean>;
}

function FindingRow({ moment, props }: { moment: CompanionAuditMoment; props: CompanionAuditSectionProps }) {
  const links = useCompanionLinks();
  const asItem = momentAsItem(moment);
  const linked = props.actionCards.get(moment.id)?.proposal ?? null;
  const canAct = linked === null && props.allowedActions.length > 0;

  const mark = (next: 'agree' | 'disagree') => void props.onMark(moment.id, moment.mark === next ? 'audit_clear' : next === 'agree' ? 'audit_agree' : 'audit_disagree');

  return (
    <li className="companion-audit-finding" aria-label={`${AUDIT_KIND_LABELS[moment.kind]} finding at ${formatClockSeconds(moment.start, { padMinutes: true })}`}>
      <div className="companion-audit-finding-head">
        <span className="companion-item-kind">{AUDIT_KIND_LABELS[moment.kind]}</span>
        <span className="meeting-transcription-state">{`[${formatClockSeconds(moment.start, { padMinutes: true })}]`}</span>
        {links?.canShowInTranscript(asItem) === true && (
          <button type="button" className="companion-link-chip" title="Scroll the transcript to where this came up" onClick={() => links.showInTranscript(asItem)}>Show in transcript</button>
        )}
      </div>
      <p className="companion-audit-why">{moment.why}</p>
      <p className="companion-audit-suggestion">{moment.suggested_text}</p>
      {linked !== null && <p className="companion-item-note">{linkedActionText(linked)}</p>}
      <div className="companion-item-actions">
        <button type="button" className="meeting-transcript-icon-button" aria-label="Good catch" title="Good catch: the Companion should have said this" aria-pressed={moment.mark === 'agree'} onClick={() => mark('agree')}>
          <ThumbUpIcon filled={moment.mark === 'agree'} />
        </button>
        <button type="button" className="meeting-transcript-icon-button" aria-label="Not needed" title="Not needed: it was right to stay quiet" aria-pressed={moment.mark === 'disagree'} onClick={() => mark('disagree')}>
          <ThumbDownIcon filled={moment.mark === 'disagree'} />
        </button>
        <CompanionActionButtons
          allowedActions={canAct ? props.allowedActions : []}
          onAction={(action) => props.onAction(moment.id, action)}
          onInvestigate={props.researchOn ? () => props.onInvestigate(moment.suggested_text) : undefined}
        />
      </div>
    </li>
  );
}

/** Did the Companion miss anything? Runs on request, shows the latest report with the counts it rests on, and lets the user mark each finding. */
export default function CompanionAuditSection(props: CompanionAuditSectionProps) {
  const { audit, auditing, isRecording, failureMessage, onRun } = props;
  const [open, setOpen] = useState(false);
  const [failed, setFailed] = useState(false);
  const requestedFrom = useRef<{ auditId: string | null; sawAuditing: boolean } | null>(null);

  useEffect(() => {
    const request = requestedFrom.current;
    if (request === null) return;
    if (auditing) request.sawAuditing = true;
    if ((audit?.audit_id ?? null) !== request.auditId) {
      requestedFrom.current = null;
      setFailed(false);
    } else if (!auditing && request.sawAuditing) {
      requestedFrom.current = null;
      setFailed(true);
    }
  }, [audit, auditing]);

  const run = async () => {
    setFailed(false);
    setOpen(true);
    requestedFrom.current = { auditId: audit?.audit_id ?? null, sawAuditing: false };
    if (!(await onRun())) requestedFrom.current = null;
  };

  const label = auditButtonLabel({ auditing, isRecording, hasAudit: audit !== null });
  return (
    <section className="companion-audit" aria-label="Audit">
      <div className="companion-audit-bar">
        <button type="button" className="companion-audit-toggle" aria-expanded={open} onClick={() => setOpen((current) => !current)}>
          {audit === null ? 'Audit' : `Audit: ${audit.moments.length} ${audit.moments.length === 1 ? 'finding' : 'findings'}`}
        </button>
        <button type="button" className="meeting-history-load-more-button" disabled={auditing} onClick={() => void run()}>{label}</button>
      </div>
      {open && (
        <div className="companion-audit-body">
          {auditing && <p className="companion-state-note" role="status">Reviewing the transcript and what the Companion weighed…</p>}
          {failed && !auditing && (
            <p className="companion-proposal-error" role="alert">{failureMessage ?? 'The audit did not finish. Try again.'}</p>
          )}
          {audit === null && !auditing && !failed && <p className="companion-state-note">An audit reads the transcript, what the Companion said and what it weighed, and lists moments where a note, to-do, agent task or research would have helped.</p>}
          {audit !== null && (
            <>
              <p className="companion-audit-counter">{auditCounterText(audit)}{audit.scope === 'so_far' ? ' (meeting still in progress)' : ''}</p>
              {audit.summary !== '' && <p className="companion-audit-summary">{audit.summary}</p>}
              <ul className="companion-audit-list">
                {audit.moments.map((moment) => (
                  <FindingRow key={`${audit.audit_id}:${moment.id}`} moment={moment} props={props} />
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
