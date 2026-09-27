export interface LocalWebPreviewSessionDTO {
  sessionId: string;
  status: 'starting' | 'running' | 'stopped' | 'error' | 'denied';
  url: string;
  host: string;
  port: number;
  pid: number | null;
  lastError: string | null;
  command: string;
  args: string[];
  cwd: string;
  createdAt: number;
  stoppedAt: number | null;
}

export interface LocalWebPreviewTransport {
  startSession(params: {
    agentTaskId: string;
    artifactId: string;
    command: string;
    args: string[];
    cwd: string;
    port: number;
  }): Promise<LocalWebPreviewSessionDTO>;
  stopSession(params: { agentTaskId: string; artifactId: string; sessionId: string }): Promise<LocalWebPreviewSessionDTO>;
  getSession(params: { agentTaskId: string; artifactId: string; sessionId: string }): Promise<LocalWebPreviewSessionDTO>;
}

function parseSessionStatus(value: unknown): LocalWebPreviewSessionDTO['status'] {
  return value === 'starting' || value === 'running' || value === 'stopped' || value === 'denied'
    ? value
    : 'error';
}

function parseSessionDto(value: unknown): LocalWebPreviewSessionDTO {
  const record = value as Record<string, unknown>;
  return {
    sessionId: String(record.session_id),
    status: parseSessionStatus(record.status),
    url: String(record.url),
    host: String(record.host),
    port: Number(record.port),
    pid: typeof record.pid === 'number' ? record.pid : null,
    lastError: typeof record.last_error === 'string' ? record.last_error : null,
    command: typeof record.command === 'string' ? record.command : '',
    args: Array.isArray(record.args) ? record.args.map(String) : [],
    cwd: typeof record.cwd === 'string' ? record.cwd : '',
    createdAt: typeof record.created_at === 'number' ? record.created_at : 0,
    stoppedAt: typeof record.stopped_at === 'number' ? record.stopped_at : null,
  };
}

export function createLocalWebPreviewTransport(getBaseUrl: () => string): LocalWebPreviewTransport {
  const request = async (path: string, init?: RequestInit): Promise<LocalWebPreviewSessionDTO> => {
    const response = await fetch(`${getBaseUrl()}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    });
    if (!response.ok) {
      throw new Error(`Local web preview request failed with status ${response.status}`);
    }
    return parseSessionDto(await response.json());
  };

  return {
    startSession: ({ agentTaskId, artifactId, command, args, cwd, port }) =>
      request(`/api/v1/agent-tasks/${agentTaskId}/artifacts/${artifactId}/local-preview/sessions`, {
        method: 'POST',
        body: JSON.stringify({ command, args, cwd, port }),
      }),
    stopSession: ({ agentTaskId, artifactId, sessionId }) =>
      request(`/api/v1/agent-tasks/${agentTaskId}/artifacts/${artifactId}/local-preview/sessions/${sessionId}/stop`, {
        method: 'POST',
      }),
    getSession: ({ agentTaskId, artifactId, sessionId }) =>
      request(`/api/v1/agent-tasks/${agentTaskId}/artifacts/${artifactId}/local-preview/sessions/${sessionId}`, {
        method: 'GET',
      }),
  };
}
