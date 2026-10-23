import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { applyAuditMark, parseCompanionAudit } from './companionAudit';
import { applyTimelineEvent, emptyTimelineState, reduceTimeline, timelineStateFromSnapshot } from './companionReducer';
import { EMPTY_COMPANION_STATUS, type CompanionSnapshot, type TimelineEvent } from './types';

const FIXTURE_PATH = resolve(
  import.meta.dirname,
  '../../../../backend/src/tests/services/meeting_companion_tests/fixtures/timeline_parity_audit.json',
);

interface AuditParityFixture {
  events: TimelineEvent[];
  expected: {
    audit: {
      audit_id: string;
      scope: string;
      summary: string;
      evaluations: number;
      spoke: number;
      covered_until: number;
      moments: Array<{ id: string; kind: string; mark: string | null }>;
    };
    last_seq: number;
  };
}

function loadFixture(): AuditParityFixture {
  return JSON.parse(readFileSync(FIXTURE_PATH, 'utf-8')) as AuditParityFixture;
}

const moment = { id: 'm1', start: 1, end: 2, kind: 'todo', why: 'Nobody owned it.', suggested_text: 'Follow up.', confidence: 0.8 };
const report = { audit_id: 'au-1', scope: 'meeting', summary: 'Ok.', moments: [moment], evaluations: 3, spoke: 1, covered_until: 9 };

describe('audit parity with the Python reducer', () => {
  it('reduces the shared fixture to the expected audit and marks', () => {
    const fixture = loadFixture();
    const state = reduceTimeline(fixture.events);
    const audit = state.audit;
    expect(audit).not.toBeNull();
    expect({
      audit: {
        audit_id: audit?.audit_id,
        scope: audit?.scope,
        summary: audit?.summary,
        evaluations: audit?.evaluations,
        spoke: audit?.spoke,
        covered_until: audit?.covered_until,
        moments: audit?.moments.map((entry) => ({ id: entry.id, kind: entry.kind, mark: entry.mark })),
      },
      last_seq: state.lastSeq,
    }).toEqual(fixture.expected);
  });

  it('keeps a good audit when a malformed report arrives', () => {
    const fixture = loadFixture();
    const good = reduceTimeline(fixture.events.slice(0, 2));
    const afterBad = applyTimelineEvent(good, fixture.events[fixture.events.length - 1]);
    expect(afterBad.audit?.audit_id).toBe('au-1');
    expect(afterBad.lastSeq).toBe(10);
  });
});

describe('audit parsing and marks', () => {
  it('defaults the optional counts and rejects a bad moment or scope', () => {
    expect(parseCompanionAudit({ audit_id: 'a', scope: 'so_far' })).toEqual({ audit_id: 'a', scope: 'so_far', summary: '', moments: [], evaluations: 0, spoke: 0, covered_until: 0 });
    expect(parseCompanionAudit({ ...report, moments: [{ ...moment, kind: 'banana' }] })).toBeNull();
    expect(parseCompanionAudit({ ...report, scope: 'later' })).toBeNull();
    expect(parseCompanionAudit('nope')).toBeNull();
  });

  it('marks, flips and clears a finding and ignores unknown findings and other actions', () => {
    const audit = parseCompanionAudit(report);
    const agreed = applyAuditMark(audit, 'm1', 'audit_agree');
    expect(agreed?.moments[0].mark).toBe('agree');
    expect(applyAuditMark(agreed, 'm1', 'audit_disagree')?.moments[0].mark).toBe('disagree');
    expect(applyAuditMark(agreed, 'm1', 'audit_clear')?.moments[0].mark).toBeNull();
    expect(applyAuditMark(agreed, 'other', 'audit_agree')).toBe(agreed);
    expect(applyAuditMark(agreed, 'm1', 'pinned')).toBe(agreed);
    expect(applyAuditMark(null, 'm1', 'audit_agree')).toBeNull();
  });

  it('restores the audit from a snapshot and treats an older snapshot as having none', () => {
    const base = { meeting_id: 'm', session_key: 's', status: EMPTY_COMPANION_STATUS, roots: [], items: [], watches: [], chat: [], retrievals: [], last_seq: 4 } as CompanionSnapshot;
    expect(timelineStateFromSnapshot(base).audit).toBeNull();
    const audit = parseCompanionAudit(report);
    expect(timelineStateFromSnapshot({ ...base, audit }).audit).toEqual(audit);
    expect(emptyTimelineState.audit).toBeNull();
  });
});
