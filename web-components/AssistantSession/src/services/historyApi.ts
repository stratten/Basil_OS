export interface AssistantOutputHistoryEntry {
  id: number;
  outputType: string;
  inputModality: string | null;
  title: string;
  outputPreview: string;
  timestamp: string;
  status: string;
  refinementCount: number;
  appName: string | null;
}

export interface AssistantOutputHistoryDetail {
  id: number;
  outputType: string;
  inputModality: string | null;
  outputText: string;
  contextText: string | null;
  explanationText: string | null;
  modelName: string | null;
  timestamp: string;
  status: string;
  refinementCount: number;
  refinements: Array<{ instruction: string; output: string; timestamp: string }>;
  appName: string | null;
  userRequest: string | null;
  processingTimeMs: number | null;
}

export class AssistantOutputHistoryApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = 'AssistantOutputHistoryApiError';
  }
}

async function requestJSON<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new AssistantOutputHistoryApiError(text || `Request failed with status ${response.status}`, response.status);
  }
  return (await response.json()) as T;
}

interface RawListItem {
  id: number;
  output_type: string;
  input_modality: string | null;
  title: string;
  output_preview: string;
  timestamp: string;
  status: string;
  refinement_count: number;
  app_name: string | null;
}

interface RawDetail {
  id: number;
  output_type: string;
  input_modality: string | null;
  output_text: string;
  context_text: string | null;
  explanation_text: string | null;
  model_name: string | null;
  timestamp: string;
  status: string;
  refinement_count: number;
  refinements: Array<{ instruction: string; output: string; timestamp: string }>;
  app_name: string | null;
  user_request: string | null;
  processing_time_ms: number | null;
}

export function materialRefinements(
  refinements: AssistantOutputHistoryDetail['refinements'],
): AssistantOutputHistoryDetail['refinements'] {
  return refinements.filter((refinement) => (
    refinement.instruction.trim().length > 0 && refinement.output.trim().length > 0
  ));
}

function toEntry(raw: RawListItem): AssistantOutputHistoryEntry {
  return {
    id: raw.id,
    outputType: raw.output_type,
    inputModality: raw.input_modality,
    title: raw.title,
    outputPreview: raw.output_preview,
    timestamp: raw.timestamp,
    status: raw.status,
    refinementCount: raw.refinement_count,
    appName: raw.app_name,
  };
}

function toDetail(raw: RawDetail): AssistantOutputHistoryDetail {
  return {
    id: raw.id,
    outputType: raw.output_type,
    inputModality: raw.input_modality,
    outputText: raw.output_text,
    contextText: raw.context_text,
    explanationText: raw.explanation_text,
    modelName: raw.model_name,
    timestamp: raw.timestamp,
    status: raw.status,
    refinementCount: raw.refinement_count,
    refinements: materialRefinements(raw.refinements ?? []),
    appName: raw.app_name,
    userRequest: raw.user_request,
    processingTimeMs: raw.processing_time_ms ?? null,
  };
}

export async function fetchHistory(
  baseUrl: string,
  filters: { inputModality?: string | null; query?: string } = {},
): Promise<AssistantOutputHistoryEntry[]> {
  const params = new URLSearchParams();
  params.set('limit', '50');
  if (filters.inputModality) params.set('input_modality', filters.inputModality);
  if (filters.query && filters.query.trim().length > 0) {
    params.set('q', filters.query.trim());
    const raw = await requestJSON<{ outputs: RawListItem[] }>(baseUrl, `/assistant-outputs/search?${params.toString()}`);
    return raw.outputs.map(toEntry);
  }
  const raw = await requestJSON<{ outputs: RawListItem[] }>(baseUrl, `/assistant-outputs?${params.toString()}`);
  return raw.outputs.map(toEntry);
}

export async function saveWritingSample(
  baseUrl: string,
  content: string,
  appName: string | null,
): Promise<void> {
  const payload: { content: string; metadata?: { app_name: string } } = { content };
  if (appName) payload.metadata = { app_name: appName };
  await requestJSON<{ status: string }>(baseUrl, '/user/writing-samples', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function fetchHistoryDetail(baseUrl: string, id: number): Promise<AssistantOutputHistoryDetail> {
  const raw = await requestJSON<RawDetail>(baseUrl, `/assistant-outputs/${id}`);
  return toDetail(raw);
}

export async function deleteHistoryEntry(baseUrl: string, id: number): Promise<void> {
  await requestJSON<{ status: string }>(baseUrl, `/assistant-outputs/${id}`, { method: 'DELETE' });
}
