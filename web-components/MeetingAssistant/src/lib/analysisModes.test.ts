import { describe, expect, it } from 'vitest';
import type { MeetingActionProposalDTO, MeetingAnalysisResultDTO } from '../bridge/types';
import {
  analysisExportFilename,
  buildAnalysisExportText,
  completedAnalysisModes,
  formatModeResult,
  formatSpeakerCount,
} from './analysisModes';

function makeProposal(overrides: Partial<MeetingActionProposalDTO> = {}): MeetingActionProposalDTO {
  return {
    id: 'proposal-1',
    sourceActionItemIndex: 0,
    sourceTask: 'Follow up with Alex',
    sourceContext: null,
    sourceTimestamp: null,
    sourceSpeaker: null,
    suggestedAgentTask: 'Draft a follow-up email to Alex',
    capabilityType: 'email_draft',
    confidence: 0.9,
    whyBasilCanHelp: 'Basil can draft the follow-up',
    missingInformation: ['recipient email'],
    requiresUserConfirmation: false,
    workspaceSource: 'meeting-1',
    executionStatus: 'proposed',
    submittedAgentTaskId: null,
    todoId: null,
    todoStatus: null,
    lastError: null,
    isEditingDraft: false,
    draftPrompt: 'Draft a follow-up email to Alex',
    liveAgentStatus: null,
    ...overrides,
  };
}

function makeResult(overrides: Partial<MeetingAnalysisResultDTO> = {}): MeetingAnalysisResultDTO {
  return {
    meetingId: 'meeting-1',
    filename: 'analysis.json',
    analyzedAt: '2026-08-14 10:00',
    modelUsed: 'local-model',
    requestedModes: ['summary', 'action_items', 'suggested_actions'],
    modesAnalyzed: ['summary', 'action_items', 'suggested_actions'],
    failedModes: null,
    customInstructions: null,
    actionItems: [{ id: 'ai-1', task: 'Send the brief', assignedTo: 'Alex', deadline: 'Friday', priority: null, context: '', timestamp: 0, speaker: null }],
    suggestedActions: [makeProposal()],
    summary: 'The team agreed to ship Friday.',
    decisions: [{ id: 'd-1', decision: 'Ship Friday', rationale: 'Customer deadline', decidedBy: null, timestamp: 0, context: '', impact: null }],
    questionsAnswers: [{ id: 'q-1', question: 'When do we ship?', answer: 'Friday', asker: 'Sam', responder: 'Alex', timestamp: 0, context: '', resolved: true }],
    sentimentAnalysis: {
      overallSentiment: 'Positive',
      sentimentScore: 0.8,
      engagementLevel: 'High',
      speakerSentiments: null,
      positiveMoments: [{ id: 'p-1', timestamp: 12, description: 'Agreement on the date', context: '' }],
      negativeMoments: [],
      toneIndicators: null,
    },
    customAnalysis: 'Focus on launch risk.',
    transcriptDuration: 125,
    speakerCount: 2,
    processingTime: 4.2,
    meetingName: 'Launch Review',
    meetingPurpose: null,
    participants: null,
    formattedDuration: '2m 5s',
    formattedProcessingTime: '4.2s',
    ...overrides,
  };
}

describe('completedAnalysisModes', () => {
  it('returns one tab per present analysis mode and never a Results fixture', () => {
    const modes = completedAnalysisModes(makeResult());
    expect(modes.map((mode) => mode.id)).toEqual([
      'action_items',
      'suggested_actions',
      'summary',
      'decisions',
      'questions',
      'sentiment',
      'custom',
    ]);
    expect(modes.map((mode) => mode.displayName)).not.toContain('Results');
  });

  it('omits modes whose payload is null', () => {
    const modes = completedAnalysisModes(makeResult({
      actionItems: null,
      suggestedActions: null,
      decisions: null,
      questionsAnswers: null,
      sentimentAnalysis: null,
      customAnalysis: null,
    }));
    expect(modes.map((mode) => mode.id)).toEqual(['summary']);
  });
});

describe('formatModeResult', () => {
  it('copies only the selected mode contents', () => {
    const result = makeResult();
    const summary = formatModeResult(result, 'summary');
    expect(summary).toContain('## Summary');
    expect(summary).toContain('The team agreed to ship Friday.');
    expect(summary).not.toContain('Send the brief');
    expect(summary).not.toContain('Basil can help');
  });

  it('uses live proposals when copying the suggested-actions tab', () => {
    const result = makeResult();
    const text = formatModeResult(result, 'suggested_actions', [
      makeProposal({ sourceTask: 'Edited live proposal', suggestedAgentTask: 'Updated draft' }),
    ]);
    expect(text).toContain('Edited live proposal');
    expect(text).toContain('Updated draft');
    expect(text).not.toContain('Follow up with Alex');
  });
});

describe('buildAnalysisExportText', () => {
  it('includes meeting metadata and every completed mode', () => {
    const text = buildAnalysisExportText(makeResult());
    expect(text).toContain('# Launch Review');
    expect(text).toContain('*Analyzed: 2026-08-14 10:00*');
    expect(text).toContain('*Model: local-model*');
    expect(text).toContain('## Action Items');
    expect(text).toContain('## To-Do Candidates');
    expect(text).toContain('## Summary');
    expect(text).toContain('## Custom Analysis');
  });

  it('omits the Transcript section when no transcript was supplied', () => {
    const text = buildAnalysisExportText(makeResult({ transcript: null }));
    expect(text).not.toContain('## Transcript');
  });

  it('appends a legibly formatted Transcript section when transcript lines are supplied', () => {
    const text = buildAnalysisExportText(makeResult({
      transcript: [
        { id: '1', text: 'Let’s ship Friday.', speakerId: null, isInterim: false, displayStart: '0:00:05', timelineStartSeconds: 5, timelineEndSeconds: 6, source: 'Microphone', lineComplete: true },
        { id: '2', text: 'Sounds good to me.', speakerId: null, isInterim: false, displayStart: '0:00:09', timelineStartSeconds: 9, timelineEndSeconds: 10, source: 'SystemAudio', lineComplete: true },
      ],
    }));
    expect(text).toContain('## Transcript');
    // Each turn gets its own `[timestamp] Speaker` header with the spoken
    // line indented beneath it, and turns are separated by a blank line.
    expect(text).toContain('[00:05] Microphone\n    Let’s ship Friday.\n\n[00:09] System Audio\n    Sounds good to me.');
  });
});

describe('analysis helpers', () => {
  it('builds a safe markdown export filename from the meeting name', () => {
    expect(analysisExportFilename(makeResult())).toBe('Launch-Review-analysis.md');
    expect(analysisExportFilename(makeResult({ meetingName: '  ???  ' }))).toBe('meeting-analysis.md');
  });

  it('formats speaker counts with the original singular/plural wording', () => {
    expect(formatSpeakerCount(1)).toBe('1 speaker');
    expect(formatSpeakerCount(3)).toBe('3 speakers');
  });
});
