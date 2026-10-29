let baseUrl = '';

export function setBaseUrl(port: number) {
  baseUrl = `http://localhost:${port}`;
}

export function isApiReady(): boolean {
  return baseUrl.length > 0;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function messageFromErrorPayload(payload: unknown): string | null {
  if (!payload || typeof payload !== 'object') return null;
  const record = payload as Record<string, unknown>;
  if (typeof record.message === 'string' && record.message.trim()) {
    return record.message.trim();
  }
  const detail = record.detail;
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }
  if (detail && typeof detail === 'object') {
    const detailRecord = detail as Record<string, unknown>;
    if (typeof detailRecord.message === 'string' && detailRecord.message.trim()) {
      return detailRecord.message.trim();
    }
    if (typeof detailRecord.error === 'string' && detailRecord.error.trim()) {
      return detailRecord.error.trim();
    }
  }
  return null;
}

async function responseErrorMessage(method: string, path: string, resp: Response): Promise<string> {
  const fallback = `API ${method} ${path} failed: ${resp.status}`;
  const responseText = await resp.text();
  if (!responseText.trim()) return fallback;
  try {
    const parsed = JSON.parse(responseText) as unknown;
    const parsedMessage = messageFromErrorPayload(parsed);
    return parsedMessage ? `${parsedMessage} (${resp.status})` : fallback;
  } catch {
    return `${responseText.trim()} (${resp.status})`;
  }
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (!baseUrl) {
    throw new Error(`API ${method} ${path} requested before host initialization`);
  }

  let resp: Response;
  try {
    resp = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    await delay(600);
    resp = await fetch(`${baseUrl}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  if (!resp.ok) {
    throw new Error(await responseErrorMessage(method, path, resp));
  }
  return resp.json();
}

// Reasoning models for the new model picker (Package 2 section 2.7,
// decision 4 in `00_README_And_Execution_Order.md`). Field shape is a
// verbatim copy of `AgentTaskResult/src/services/api.ts`'s own
// `ReasoningModel`/`getReasoningModels` — same backend endpoint, same
// response shape, intentionally not shared/imported across packages per the
// established per-package-copy convention (section 5.9).
export interface ReasoningModel {
  id: string;
  name: string;
  display_name: string;
  provider: string;
  category: 'local' | 'api' | 'custom';
  is_api_model: boolean;
  description?: string;
}

export async function getReasoningModels(): Promise<{
  models: ReasoningModel[];
  current_model: string;
  api_models_enabled: boolean;
}> {
  return request('GET', '/settings/api_models/reasoning');
}
