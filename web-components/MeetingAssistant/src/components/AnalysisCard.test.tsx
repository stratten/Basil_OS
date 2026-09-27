import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AnalysisMetadataEntryDTO, MeetingUIStateDTO } from '../bridge/types';
import AnalysisCard from './AnalysisCard';

const intents = vi.hoisted(() => ({ deleteAnalysis: vi.fn(), setAnalysisConfiguration: vi.fn(), startAnalysis: vi.fn(), viewAnalysis: vi.fn() }));
vi.mock('../bridge/meetingBridge', () => intents);

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

describe('AnalysisCard', () => {
  beforeEach(() => Object.values(intents).forEach((mock) => mock.mockReset()));

  it('renders full configuration and four-column history', () => {
    render(<AnalysisCard ui={ui} analysisHistory={history} />);
    expect(screen.getByText('Analyze transcript to extract insights')).toBeInTheDocument();
    expect(screen.getByText('Analysis Types:')).toBeInTheDocument();
    const analysisTypeLabels = ['Action Items', 'To-Do Candidates', 'Summary', 'Key Decisions', 'Questions & Answers', 'Sentiment Analysis', 'Custom Analysis'];
    for (const label of analysisTypeLabels) {
      const modeLabel = screen.getAllByText(label).find((node) => node.closest('.meeting-analysis-mode-checkbox'));
      expect(modeLabel?.closest('label')?.querySelector('.meeting-analysis-mode-icon')).not.toBeNull();
    }
    expect(screen.getByLabelText('Custom Instructions (optional):')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyze Meeting' }).querySelector('svg')).not.toBeNull();
    expect(screen.getByText('Date & Time')).toBeInTheDocument();
    expect(screen.getByText('Analysis Types')).toBeInTheDocument();
    expect(screen.getByText('Model')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
  });

  it('uses a rotating chevron disclosure and preserves intents', async () => {
    const user = userEvent.setup();
    render(<AnalysisCard ui={ui} analysisHistory={history} />);
    const disclosure = screen.getByRole('button', { name: 'Analysis' });
    expect(disclosure.querySelector('.meeting-analysis-chevron.is-expanded')).not.toBeNull();
    await user.click(disclosure);
    expect(intents.setAnalysisConfiguration).toHaveBeenCalledWith({ isExpanded: false });
    await user.click(screen.getByRole('button', { name: 'View' }));
    expect(intents.viewAnalysis).toHaveBeenCalledWith('analysis.json');
  });

  it('renders one analysis progress label with a normal-weight percentage', () => {
    render(<AnalysisCard ui={{
      ...ui,
      isAnalyzing: true,
      activeAnalysisMeetingId: 'meeting-1',
      displayedMeetingWorkOwnerId: 'meeting-1',
      analysisProgress: 0.42,
      analysisMessage: 'Analyzing: Summary…',
      currentAnalysisMode: 'Summary',
    }} analysisHistory={[]} />);
    expect(screen.getAllByText('Analyzing: Summary…')).toHaveLength(1);
    const percentage = screen.getByText('42%');
    expect(percentage).toHaveClass('meeting-analysis-progress-percent');
    expect(percentage.tagName).toBe('SPAN');
  });

  it('does not display another meeting’s analysis progress or completion status', () => {
    const { rerender } = render(<AnalysisCard ui={{
      ...ui,
      isAnalyzing: true,
      activeAnalysisMeetingId: 'meeting-a',
      displayedMeetingWorkOwnerId: 'meeting-b',
      analysisProgress: 0.42,
      analysisMessage: 'Analyzing: Summary…',
      analysisJustCompleted: true,
      analysisStartedAutomatically: true,
    }} analysisHistory={[]} />);

    expect(screen.queryByText('Analyzing: Summary…')).not.toBeInTheDocument();
    expect(screen.queryByText('Analysis complete')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Analyze Meeting' })).toBeDisabled();

    rerender(<AnalysisCard ui={{
      ...ui,
      isAnalysisSectionExpanded: false,
      isAnalyzing: true,
      activeAnalysisMeetingId: 'meeting-a',
      displayedMeetingWorkOwnerId: 'meeting-b',
      analysisStartedAutomatically: true,
    }} analysisHistory={[]} />);
    expect(screen.queryByText('Automatic analysis running')).not.toBeInTheDocument();
  });
});
