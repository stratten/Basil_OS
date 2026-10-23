import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AnalysisMetadataEntryDTO, MeetingUIStateDTO } from '../bridge/types';
import AnalysisCard from './AnalysisCard';

vi.mock('../bridge/meetingBridge', () => ({ deleteAnalysis: vi.fn(), setAnalysisConfiguration: vi.fn(), startAnalysis: vi.fn(), viewAnalysis: vi.fn() }));

const ui = {
  isAnalysisSectionExpanded: true,
  selectedAnalysisModes: ['summary'],
  analysisCustomInstructions: '',
  selectedAnalysisModelId: 'local-model',
  localAnalysisModels: [{ id: 'local-model', name: 'local-model', displayName: 'Local Model', provider: 'local', isApiModel: false }],
  apiAnalysisModels: [],
  useApiModelsForAnalysis: false,
  isLoadingAnalysisModels: false,
  isAnalyzing: false,
  analysisProgress: 0,
  analysisMessage: '',
  currentAnalysisMode: null,
  analysisJustCompleted: false,
  analysisStartedAutomatically: false,
  hasTranscription: true,
  isLoadingAnalysisHistory: false,
} as unknown as MeetingUIStateDTO;

const history: AnalysisMetadataEntryDTO[] = [{
  id: 'analysis.json',
  timestamp: '2026-08-14T15:00:00Z',
  filename: 'analysis.json',
  modes: ['summary'],
  modelUsed: 'local-model',
  formattedDate: '2026-08-14 11:00 am',
  modesDisplay: 'Summary',
  shortModelName: 'Local Model',
}];

describe('AnalysisCard refresh continuity', () => {
  it('keeps previous analyses visible while analysis history reloads', () => {
    const { container } = render(<AnalysisCard ui={{ ...ui, isLoadingAnalysisHistory: true }} analysisHistory={history} />);
    expect(container.querySelector('.meeting-analysis-history-loading')).toBeNull();
    expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument();
  });

  it('shows the history loading row only when no analyses are visible', () => {
    const { container } = render(<AnalysisCard ui={{ ...ui, isLoadingAnalysisHistory: true }} analysisHistory={[]} />);
    expect(container.querySelector('.meeting-analysis-history-loading')).not.toBeNull();
  });

  it('collapses the analysis body through a presence region', () => {
    const { container, rerender } = render(<AnalysisCard ui={ui} analysisHistory={history} />);
    expect(container.querySelector('.meeting-analysis-configuration')?.parentElement?.hasAttribute('data-presence-phase')).toBe(true);
    rerender(<AnalysisCard ui={{ ...ui, isAnalysisSectionExpanded: false }} analysisHistory={history} />);
    expect(container.querySelector('.meeting-analysis-configuration')).toBeNull();
  });
});
