import { describe, expect, it } from 'vitest';
import { applyMeetingBridgeEvent, initialMeetingState, mergeTranscript } from './meetingReducer';
import type { MeetingBridgeEvent, MeetingUIStateDTO, TranscriptLineDTO } from '../bridge/types';

const baseUi = {} as MeetingUIStateDTO;

describe('applyMeetingBridgeEvent', () => {
  it('applies a snapshot unconditionally, setting connected=true', () => {
    const event: MeetingBridgeEvent = { type: 'snapshot', revision: 0, selectionGeneration: 0, protocolVersion: 4, ui: baseUi, transcript: [], history: [] };
    const next = applyMeetingBridgeEvent(initialMeetingState, event);
    expect(next.connected).toBe(true);
    expect(next.revision).toBe(0);
  });

  it('drops a delta whose revision is not strictly greater than the applied revision', () => {
    const snapshot = applyMeetingBridgeEvent(initialMeetingState, {
      type: 'snapshot',
      revision: 5,
      selectionGeneration: 0,
      protocolVersion: 4,
    });
    const stale: MeetingBridgeEvent = { type: 'sessionDelta', revision: 5, selectionGeneration: 0, protocolVersion: 4, ui: baseUi };
    const next = applyMeetingBridgeEvent(snapshot, stale);
    expect(next).toBe(snapshot);
  });

  it('rejects events from an unsupported protocol version', () => {
    const incompatible = applyMeetingBridgeEvent(initialMeetingState, {
      type: 'snapshot',
      revision: 0,
      selectionGeneration: 0,
      protocolVersion: 3,
      ui: baseUi,
    });
    expect(incompatible).toBe(initialMeetingState);
  });

  it('drops a transcriptDelta whose selectionGeneration is older than the applied selection', () => {
    const snapshot = applyMeetingBridgeEvent(initialMeetingState, {
      type: 'snapshot',
      revision: 0,
      selectionGeneration: 2,
      protocolVersion: 4,
    });
    const staleSelection: MeetingBridgeEvent = {
      type: 'transcriptDelta',
      revision: 1,
      selectionGeneration: 1,
      protocolVersion: 4,
      transcript: [{ id: 'x', text: 'stale', speakerId: null, isInterim: false, displayStart: null, timelineStartSeconds: null, timelineEndSeconds: null, source: null, lineComplete: true }],
    };
    const next = applyMeetingBridgeEvent(snapshot, staleSelection);
    expect(next.transcript).toEqual([]);
  });

  it('applies a current validationError and consumes its revision', () => {
    const next = applyMeetingBridgeEvent(initialMeetingState, {
      type: 'validationError',
      revision: 0,
      selectionGeneration: 0,
      protocolVersion: 4,
      validationErrorCode: 'stale_process',
      validationErrorMessage: 'That app is no longer available.',
    });
    expect(next.lastValidationError?.code).toBe('stale_process');
    expect(next.revision).toBe(0);
  });

  it('advances selection generation with the session delta so stale selected-domain data is rejected', () => {
    const selected = applyMeetingBridgeEvent(initialMeetingState, {
      type: 'sessionDelta',
      revision: 1,
      selectionGeneration: 3,
      protocolVersion: 4,
      ui: baseUi,
    });
    const staleTranscript = applyMeetingBridgeEvent(selected, {
      type: 'transcriptDelta',
      revision: 2,
      selectionGeneration: 2,
      protocolVersion: 4,
      transcript: [{ id: 'stale', text: 'wrong meeting', speakerId: null, isInterim: false, displayStart: null, timelineStartSeconds: null, timelineEndSeconds: null, source: null, lineComplete: true }],
    });
    expect(selected.selectionGeneration).toBe(3);
    expect(staleTranscript).toBe(selected);
  });

  it('clears a stale analysis result while a different historical result loads', () => {
    const withResult = {
      ...initialMeetingState,
      connected: true,
      revision: 1,
      analysisResult: {} as any,
      proposals: [{} as any],
    };
    const next = applyMeetingBridgeEvent(withResult, {
      type: 'sessionDelta',
      revision: 2,
      selectionGeneration: 0,
      protocolVersion: 4,
      ui: { ...baseUi, isLoadingAnalysisResult: true },
    });
    expect(next.analysisResult).toBeNull();
    expect(next.proposals).toEqual([]);
  });

  it('clears stale proposal statuses when a new analysis result arrives', () => {
    const previous = {
      ...initialMeetingState,
      connected: true,
      revision: 1,
      analysisResult: { filename: 'old-analysis.json' } as any,
      proposals: [{ id: 'old', executionStatus: 'added_to_todos', todoId: 'todo-old' }] as any,
    };
    const next = applyMeetingBridgeEvent(previous, {
      type: 'analysisResultDelta',
      revision: 2,
      selectionGeneration: 0,
      protocolVersion: 4,
      analysisResult: { filename: 'new-analysis.json' } as any,
    });
    expect(next.analysisResult?.filename).toBe('new-analysis.json');
    expect(next.proposals).toEqual([]);
  });
});

describe('mergeTranscript', () => {
  const line = (id: string, text: string, isInterim = false): TranscriptLineDTO => ({
    id,
    text,
    speakerId: null,
    isInterim,
    displayStart: null,
    timelineStartSeconds: null,
    timelineEndSeconds: null,
    source: null,
    lineComplete: true,
  });

  it('preserves referential identity for unchanged rows', () => {
    const previous = [line('a', 'hello'), line('b', 'world')];
    const next = mergeTranscript(previous, [line('a', 'hello'), line('b', 'world')]);
    expect(next[0]).toBe(previous[0]);
    expect(next[1]).toBe(previous[1]);
  });

  it('returns a new object only for a row whose text or interim flag changed', () => {
    const previous = [line('a', 'hello')];
    const next = mergeTranscript(previous, [line('a', 'hello world')]);
    expect(next[0]).not.toBe(previous[0]);
    expect(next[0].text).toBe('hello world');
  });

  it('returns a new object when corrected speaker metadata changes without changing text', () => {
    const previous = [line('a', 'hello')];
    const corrected = { ...line('a', 'hello'), speakerId: 'Speaker 1' };
    const next = mergeTranscript(previous, [corrected]);
    expect(next[0]).toBe(corrected);
  });
});

describe('transcript patches', () => {
  const line = (id: string, text: string, isInterim = false): TranscriptLineDTO => ({
    id,
    text,
    speakerId: null,
    isInterim,
    displayStart: null,
    timelineStartSeconds: null,
    timelineEndSeconds: null,
    source: null,
    lineComplete: true,
  });

  const applyPatch = (transcript: TranscriptLineDTO[], patch: { orderedIDs: string[]; upserts: TranscriptLineDTO[]; removedIDs: string[] }) => applyMeetingBridgeEvent(
    {
      ...initialMeetingState,
      connected: true,
      revision: 0,
      selectionGeneration: 0,
      transcript,
    },
    {
      type: 'transcriptDelta',
      revision: 1,
      selectionGeneration: 0,
      protocolVersion: 4,
      transcriptPatch: patch,
    },
  );

  it('appends a row while preserving preceding row references', () => {
    const first = line('first', 'First');
    const second = line('second', 'Second');
    const next = applyPatch([first], { orderedIDs: ['first', 'second'], upserts: [second], removedIDs: [] });

    expect(next.transcript).toEqual([first, second]);
    expect(next.transcript[0]).toBe(first);
  });

  it('replaces only an updated interim row', () => {
    const stable = line('stable', 'Stable');
    const interim = line('interim', 'Partial', true);
    const corrected = line('interim', 'Complete');
    const next = applyPatch([stable, interim], { orderedIDs: ['stable', 'interim'], upserts: [corrected], removedIDs: [] });

    expect(next.transcript[0]).toBe(stable);
    expect(next.transcript[1]).toBe(corrected);
  });

  it('removes obsolete rows and applies the supplied order', () => {
    const first = line('first', 'First');
    const second = line('second', 'Second');
    const third = line('third', 'Third');
    const next = applyPatch([first, second, third], { orderedIDs: ['third', 'first'], upserts: [], removedIDs: ['second'] });

    expect(next.transcript.map((entry) => entry.id)).toEqual(['third', 'first']);
    expect(next.transcript[0]).toBe(third);
    expect(next.transcript[1]).toBe(first);
  });
});
