import { describe, expect, it } from 'vitest';
import { groupedAnalysisModels } from './analysisModelOptions';

const local = { id: 'local-1', name: 'local-one', displayName: 'Local One', category: 'local' } as const;
const api = { id: 'api-1', name: 'api-one', displayName: 'Api One', category: 'api' } as const;

describe('groupedAnalysisModels', () => {
  it('lists only local models unless API models are enabled', () => {
    const ui = { localAnalysisModels: [local], apiAnalysisModels: [api], useApiModelsForAnalysis: false };
    expect(groupedAnalysisModels(ui as never).map((model) => model.id)).toEqual(['local-1']);
    expect(groupedAnalysisModels({ ...ui, useApiModelsForAnalysis: true } as never).map((model) => model.id)).toEqual(['local-1', 'api-1']);
  });

  it('maps displayName to display_name and keeps the category', () => {
    const result = groupedAnalysisModels({ localAnalysisModels: [local], apiAnalysisModels: [], useApiModelsForAnalysis: false } as never);
    expect(result).toEqual([{ id: 'local-1', name: 'local-one', display_name: 'Local One', category: 'local' }]);
  });

  it('returns an empty list when no models are available', () => {
    expect(groupedAnalysisModels({ localAnalysisModels: [], apiAnalysisModels: [], useApiModelsForAnalysis: true } as never)).toEqual([]);
  });
});
