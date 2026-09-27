import type { MeetingActionProposalDTO, MeetingAnalysisResultDTO } from '../bridge/types';
import { buildTranscriptRows, formatTranscriptForCopy } from './transcriptFormatting';

export type AnalysisModeId =
  | 'action_items'
  | 'suggested_actions'
  | 'summary'
  | 'decisions'
  | 'questions'
  | 'sentiment'
  | 'custom';

export interface AnalysisModeDefinition {
  id: AnalysisModeId;
  displayName: string;
  description: string;
}

export const ANALYSIS_MODE_ORDER: AnalysisModeDefinition[] = [
  { id: 'action_items', displayName: 'Action Items', description: 'Extract tasks and action items' },
  { id: 'suggested_actions', displayName: 'To-Do Candidates', description: 'Review durable follow-ups Basil identified' },
  { id: 'summary', displayName: 'Summary', description: 'Generate meeting summary' },
  { id: 'decisions', displayName: 'Key Decisions', description: 'Identify key decisions' },
  { id: 'questions', displayName: 'Questions & Answers', description: 'Extract Q&A pairs' },
  { id: 'sentiment', displayName: 'Sentiment Analysis', description: 'Analyze tone and engagement' },
  { id: 'custom', displayName: 'Custom Analysis', description: 'Custom analysis' },
];

export function completedAnalysisModes(result: MeetingAnalysisResultDTO): AnalysisModeDefinition[] {
  return ANALYSIS_MODE_ORDER.filter((mode) => hasCompletedMode(result, mode.id));
}

export function hasCompletedMode(result: MeetingAnalysisResultDTO, mode: AnalysisModeId): boolean {
  switch (mode) {
    case 'action_items':
      return result.actionItems != null;
    case 'suggested_actions':
      return result.suggestedActions != null;
    case 'summary':
      return result.summary != null;
    case 'decisions':
      return result.decisions != null;
    case 'questions':
      return result.questionsAnswers != null;
    case 'sentiment':
      return result.sentimentAnalysis != null;
    case 'custom':
      return result.customAnalysis != null;
  }
}

export function formatModeResult(
  result: MeetingAnalysisResultDTO,
  mode: AnalysisModeId,
  proposals: MeetingActionProposalDTO[] = result.suggestedActions ?? [],
): string {
  const definition = ANALYSIS_MODE_ORDER.find((entry) => entry.id === mode);
  let text = `## ${definition?.displayName ?? mode}\n\n`;
  text += `*${definition?.description ?? ''}*\n\n`;

  switch (mode) {
    case 'action_items':
      (result.actionItems ?? []).forEach((item, index) => {
        text += `${index + 1}. **${item.task}**\n`;
        if (item.assignedTo) text += `   - Assigned to: ${item.assignedTo}\n`;
        if (item.deadline) text += `   - Due: ${item.deadline}\n`;
        text += '\n';
      });
      break;
    case 'suggested_actions':
      proposals.forEach((proposal, index) => {
        text += `${index + 1}. **${proposal.sourceTask}**\n`;
        text += `   - Basil can help: ${proposal.whyBasilCanHelp}\n`;
        text += `   - Suggested task: ${proposal.suggestedAgentTask}\n`;
        if (proposal.missingInformation.length > 0) {
          text += `   - Needs: ${proposal.missingInformation.join(', ')}\n`;
        }
        text += '\n';
      });
      break;
    case 'summary':
      if (result.summary) text += `${result.summary}\n\n`;
      break;
    case 'decisions':
      (result.decisions ?? []).forEach((decision, index) => {
        text += `${index + 1}. **${decision.decision}**\n`;
        if (decision.rationale) text += `   - Rationale: ${decision.rationale}\n`;
        text += '\n';
      });
      break;
    case 'questions':
      (result.questionsAnswers ?? []).forEach((qa) => {
        text += `**Q:** ${qa.question}\n`;
        text += `**A:** ${qa.answer}\n`;
        if (qa.asker) text += `*Asker: ${qa.asker}*\n`;
        if (qa.responder) text += `*Responder: ${qa.responder}*\n`;
        text += '\n';
      });
      break;
    case 'sentiment':
      if (result.sentimentAnalysis) {
        const sentiment = result.sentimentAnalysis;
        text += `**Overall Sentiment:** ${sentiment.overallSentiment}\n`;
        text += `**Engagement Level:** ${sentiment.engagementLevel}\n\n`;
        if (sentiment.positiveMoments && sentiment.positiveMoments.length > 0) {
          text += '### Positive Moments\n';
          for (const moment of sentiment.positiveMoments) {
            text += `- ${moment.description}\n`;
          }
          text += '\n';
        }
        if (sentiment.negativeMoments && sentiment.negativeMoments.length > 0) {
          text += '### Negative Moments\n';
          for (const moment of sentiment.negativeMoments) {
            text += `- ${moment.description}\n`;
          }
          text += '\n';
        }
      }
      break;
    case 'custom':
      if (result.customInstructions?.trim()) {
        text += `**Request:**\n\n${result.customInstructions}\n\n`;
      }
      if (result.customAnalysis) text += `${result.customAnalysis}\n\n`;
      break;
  }

  return text;
}

export function buildAnalysisExportText(
  result: MeetingAnalysisResultDTO,
  proposals: MeetingActionProposalDTO[] = result.suggestedActions ?? [],
): string {
  let fullText = `# ${result.meetingName ?? 'Meeting Analysis'}\n\n`;
  fullText += `*Analyzed: ${result.analyzedAt}*\n\n`;
  fullText += `*Model: ${result.modelUsed}*\n\n`;
  for (const mode of completedAnalysisModes(result)) {
    fullText += formatModeResult(result, mode.id, proposals);
    fullText += '\n---\n\n';
  }
  if (result.transcript && result.transcript.length > 0) {
    fullText += '## Transcript\n\n';
    fullText += formatTranscriptForCopy(buildTranscriptRows(result.transcript));
    fullText += '\n';
  }
  return fullText;
}

export function analysisExportFilename(result: MeetingAnalysisResultDTO): string {
  const stem = (result.meetingName ?? 'meeting').trim().replace(/[^a-z0-9_-]+/gi, '-').replace(/^-+|-+$/g, '') || 'meeting';
  return `${stem}-analysis.md`;
}

export function formatSpeakerCount(count: number): string {
  return `${count} speaker${count === 1 ? '' : 's'}`;
}
