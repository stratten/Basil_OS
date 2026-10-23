import type { SharedReasoningModel } from '../../../shared/ReasoningModelPicker';
import type { MeetingUIStateDTO } from '../bridge/types';

/** The model list the shared reasoning picker shows, identical for the Analysis card and the Companion pane. */
export function groupedAnalysisModels(
  ui: Pick<MeetingUIStateDTO, 'localAnalysisModels' | 'apiAnalysisModels' | 'useApiModelsForAnalysis'>,
): SharedReasoningModel[] {
  const models = [...ui.localAnalysisModels, ...(ui.useApiModelsForAnalysis ? ui.apiAnalysisModels : [])];
  return models.map((model) => ({
    id: model.id,
    name: model.name,
    display_name: model.displayName,
    category: model.category,
  }));
}
