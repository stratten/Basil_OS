import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CompanionConsideredBar from './CompanionConsideredBar';
import CompanionConsideredRow from './CompanionConsideredRow';
import CompanionItemCard from './CompanionItemCard';
import { consideredCounterText, consideredHeadline, parseEvaluationEvent } from './companionEvaluations';
import { MAX_DERIVED_EVALUATIONS, applyTimelineEvent, emptyTimelineState, parseCompanionItem, reduceTimeline, timelineStateFromSnapshot } from './companionReducer';
import { countsAsUnseen, selectCompanionStream } from './companionStreamSelectors';
import { getCompanionView, resetCompanionViews } from './companionViewStore';
import { EMPTY_COMPANION_STATUS, type CompanionItem, type CompanionSnapshot, type TimelineEvent } from './types';

function evaluation(seq: number, payload: Record<string, unknown> = {}): TimelineEvent {
  return { id: `ev-${seq}`, seq, kind: 'evaluation', meeting_time: seq * 10, wall_time: '2026-01-01T00:00:00Z', payload: { trigger: 'periodic', considered: 'Small talk, nothing to add.', kept: 0, candidates: [], ...payload } };
}

function item(overrides: Partial<CompanionItem> = {}): CompanionItem {
  return {
    id: 'i1',
    seq: 4,
    kind: 'insight',
    text: 'Nobody owns the follow-up.',
    confidence: 0.7,
    citations: [],
    no_source: false,
    transcript_range: { start: 5, end: 9, turn_ids: [] },
    trigger: 'periodic',
    watch_id: null,
    truncated: false,
    pinned: false,
    dismissed: false,
    ...overrides,
  };
}

describe('the evaluation reducer', () => {
  it('collects ledger events, counts past the cap and ignores nothing else', () => {
    const events = Array.from({ length: MAX_DERIVED_EVALUATIONS + 4 }, (_, index) => evaluation(index + 1));
    const state = reduceTimeline(events);
    expect(state.evaluationTotal).toBe(MAX_DERIVED_EVALUATIONS + 4);
    expect(state.evaluations).toHaveLength(MAX_DERIVED_EVALUATIONS);
    expect(state.evaluations[state.evaluations.length - 1].seq).toBe(MAX_DERIVED_EVALUATIONS + 4);
    expect(state.items).toEqual([]);
  });

  it('seeds from a snapshot, keeps the larger total, and tolerates a snapshot without the fields', () => {
    const base: CompanionSnapshot = { meeting_id: 'm', session_key: 's', status: EMPTY_COMPANION_STATUS, roots: [], items: [], watches: [], chat: [], retrievals: [], last_seq: 9 };
    expect(timelineStateFromSnapshot(base)).toMatchObject({ evaluations: [], evaluationTotal: 0 });
    const seeded = timelineStateFromSnapshot({ ...base, evaluations: [evaluation(8)], evaluation_total: 67 });
    expect(seeded.evaluationTotal).toBe(67);
    const next = applyTimelineEvent(seeded, evaluation(10));
    expect(next.evaluationTotal).toBe(68);
    expect(next.evaluations).toHaveLength(2);
  });

  it('keeps the rationale on an item and omits it when empty', () => {
    const raw = { ...item(), rationale: 'Two people agreed on Friday but nobody owns it.' };
    expect(parseCompanionItem(raw)?.rationale).toBe('Two people agreed on Friday but nobody owns it.');
    expect(parseCompanionItem({ ...item(), rationale: '' })?.rationale).toBeUndefined();
    expect(parseCompanionItem(item())?.rationale).toBeUndefined();
  });
});

describe('evaluation presentation', () => {
  it('reads a malformed payload without throwing', () => {
    const record = parseEvaluationEvent({ ...evaluation(1), payload: { candidates: 'x', gate_waits: [1], kept: 'many' } });
    expect(record).toMatchObject({ trigger: 'periodic', kept: 0, candidates: [], gateWaits: [], latencyMs: null, error: null });
  });

  it('words the counter and the headline', () => {
    expect(consideredCounterText(67, 12)).toBe('Considered 67 times, spoke 12');
    expect(consideredCounterText(1, 0)).toBe('Considered 1 time, spoke 0');
    expect(consideredHeadline(parseEvaluationEvent(evaluation(1, { considered: '' })))).toBe('Nothing worth adding.');
    expect(consideredHeadline(parseEvaluationEvent(evaluation(1, { considered: '', kept: 1 })))).toBe('Wrote a note.');
    expect(consideredHeadline(parseEvaluationEvent(evaluation(1, { error: 'timeout' })))).toBe('Could not check this time (timeout)');
  });
});

describe('the Considered stream rows', () => {
  const timeline = { ...emptyTimelineState, items: [item({ seq: 4 })], evaluations: [evaluation(3), evaluation(5)] };

  it('are absent by default and interleave by arrival when shown', () => {
    expect(selectCompanionStream(timeline).map((entry) => entry.key)).toEqual(['item:i1']);
    expect(selectCompanionStream(timeline, { showConsidered: true }).map((entry) => entry.key)).toEqual(['eval:ev-3', 'item:i1', 'eval:ev-5']);
  });

  it('never count as unseen', () => {
    const rows = selectCompanionStream(timeline, { showConsidered: true });
    expect(rows.filter(countsAsUnseen).map((entry) => entry.key)).toEqual(['item:i1']);
  });

  it('start switched off in the view store', () => {
    resetCompanionViews();
    expect(getCompanionView('m1').showConsidered).toBe(false);
  });
});

describe('Considered components', () => {
  it('shows the counter and flips the toggle', () => {
    const onToggle = vi.fn();
    render(<CompanionConsideredBar total={67} spoke={12} shown={false} onToggle={onToggle} />);
    expect(screen.getByText('Considered 67 times, spoke 12')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show what it considered' }));
    expect(onToggle).toHaveBeenCalledWith(true);
  });

  it('labels the toggle for hiding once the rows are shown', () => {
    render(<CompanionConsideredBar total={1} spoke={0} shown onToggle={vi.fn()} />);
    expect(screen.getByRole('button', { name: 'Hide what it considered' }).getAttribute('aria-pressed')).toBe('true');
  });

  it('explains a quiet check, its dropped candidate and the gate waits', () => {
    render(
      <CompanionConsideredRow
        event={evaluation(6, {
          trigger: 'question',
          new_lines: 1,
          candidates: [{ kind: 'insight', text: 'A weak idea.', confidence: 0.42, outcome: 'confidence_floor' }],
          gate_waits: { 'few lines': 3 },
        })}
      />,
    );
    expect(screen.getByText('Stayed quiet')).toBeTruthy();
    expect(screen.getByText('Small talk, nothing to add.')).toBeTruthy();
    expect(screen.getByText(/Looked at a question, 1 new line/)).toBeTruthy();
    expect(screen.getByText(/not confident enough/)).toBeTruthy();
    expect(screen.getByText(/waiting for more speech x3/)).toBeTruthy();
  });

  it('says a result that arrived too late was thrown away, and a long error stays inside the row', () => {
    render(<CompanionConsideredRow event={evaluation(7, { discarded: 'stale', kept: 1, error: 'x'.repeat(300) })} />);
    expect(screen.getByText('The result arrived too late and was thrown away.')).toBeTruthy();
    expect(screen.getByText('Stayed quiet')).toBeTruthy();
  });
});

describe('the Why this? disclosure', () => {
  const props = { watchTopic: null, onFeedback: vi.fn(async () => true), canInvestigate: false, onInvestigate: vi.fn() };

  it('appears only when the item carries a rationale', () => {
    const { rerender } = render(<CompanionItemCard item={item({ rationale: 'Friday deadline with no owner.' })} {...props} />);
    expect(screen.getByText('Why this?')).toBeTruthy();
    expect(screen.getByText('Friday deadline with no owner.')).toBeTruthy();
    rerender(<CompanionItemCard item={item()} {...props} />);
    expect(screen.queryByText('Why this?')).toBeNull();
  });
});
