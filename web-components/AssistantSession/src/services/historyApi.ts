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

export type SampleContextType = 'email_reply' | 'email_compose' | 'social_media' | 'document';

export const SAMPLE_CONTEXT_OPTIONS: ReadonlyArray<{ value: SampleContextType; label: string }> = [
  { value: 'email_reply', label: 'Email Reply' },
  { value: 'email_compose', label: 'Email Compose' },
  { value: 'social_media', label: 'Social Media' },
  { value: 'document', label: 'Document' },
];

export interface SavedHistorySample {
  id: string;
  content: string;
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
  sampleContextType: SampleContextType | null;
  recipient: string | null;
  savedSample: SavedHistorySample | null;
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
  sample_context_type?: string | null;
  recipient?: string | null;
  saved_sample?: { id: string; content: string; context_type: string } | null;
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

function toSampleContextType(value: string | null | undefined): SampleContextType | null {
  return SAMPLE_CONTEXT_OPTIONS.some((option) => option.value === value) ? (value as SampleContextType) : null;
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
    sampleContextType: toSampleContextType(raw.sample_context_type),
    recipient: raw.recipient ?? null,
    savedSample: raw.saved_sample ? { id: raw.saved_sample.id, content: raw.saved_sample.content } : null,
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

export async function saveHistoryOutputAsSample(
  baseUrl: string,
  id: number,
  content: string,
  contextType: SampleContextType | null,
): Promise<SavedHistorySample> {
  const payload: { content: string; context_type?: SampleContextType } = { content };
  if (contextType) payload.context_type = contextType;
  const raw = await requestJSON<{ sample_id: string; content: string }>(baseUrl, `/assistant-outputs/${id}/save-sample`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return { id: raw.sample_id, content: raw.content };
}

export async function updateSavedSampleContent(
  baseUrl: string,
  sampleId: string,
  content: string,
): Promise<SavedHistorySample> {
  const raw = await requestJSON<{ sample_id: string; content: string }>(
    baseUrl,
    `/user/writing-samples/${encodeURIComponent(sampleId)}`,
    { method: 'PATCH', body: JSON.stringify({ content }) },
  );
  return { id: raw.sample_id, content: raw.content };
}

export async function fetchHistoryDetail(baseUrl: string, id: number): Promise<AssistantOutputHistoryDetail> {
  const raw = await requestJSON<RawDetail>(baseUrl, `/assistant-outputs/${id}`);
  return toDetail(raw);
}

export async function deleteHistoryEntry(baseUrl: string, id: number): Promise<void> {
  await requestJSON<{ status: string }>(baseUrl, `/assistant-outputs/${id}`, { method: 'DELETE' });
}
