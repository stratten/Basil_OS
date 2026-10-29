import { request } from '../../../services/api';

export interface ManagedFileVersion {
  id: string;
  rootTaskId: string;
  agentTaskId: string;
  canonicalPath: string;
  operation: 'create' | 'overwrite' | 'append' | 'rollback';
  origin: 'model' | 'user';
  postImageSizeBytes: number | null;
  restoresChangeId: string | null;
  createdAt: string;
  appliedAt: string | null;
}

export interface RestoreManagedFileVersionResult {
  success: boolean;
  changeId?: string;
  canonicalPath?: string;
  restoredFromChangeId?: string;
  error?: string;
  errorType?: string;
}

export interface ManagedFileVersionContent {
  changeId: string;
  canonicalPath: string;
  content: string | null;
  truncated: boolean;
  byteSize: number | null;
}

function fromApiVersion(raw: Record<string, unknown>): ManagedFileVersion {
  return {
    id: String(raw.id),
    rootTaskId: String(raw.root_task_id),
    agentTaskId: String(raw.agent_task_id),
    canonicalPath: String(raw.canonical_path),
    operation: raw.operation as ManagedFileVersion['operation'],
    origin: raw.origin as ManagedFileVersion['origin'],
    postImageSizeBytes: typeof raw.post_image_size_bytes === 'number' ? raw.post_image_size_bytes : null,
    restoresChangeId: typeof raw.restores_change_id === 'string' ? raw.restores_change_id : null,
    createdAt: String(raw.created_at),
    appliedAt: typeof raw.applied_at === 'string' ? raw.applied_at : null,
  };
}

export async function listManagedFileVersions(canonicalPath: string): Promise<ManagedFileVersion[]> {
  const body = await request<{ canonical_path: string; versions: Record<string, unknown>[] }>(
    'GET',
    `/api/v1/agent-tasks/managed-file-history/versions?canonical_path=${encodeURIComponent(canonicalPath)}`,
  );
  return body.versions.map(fromApiVersion);
}

export async function getManagedFileVersionContent(changeId: string): Promise<ManagedFileVersionContent> {
  const body = await request<Record<string, unknown>>(
    'GET',
    `/api/v1/agent-tasks/managed-file-history/versions/${encodeURIComponent(changeId)}/content`,
  );
  return {
    changeId: String(body.change_id),
    canonicalPath: String(body.canonical_path),
    content: typeof body.content === 'string' ? body.content : null,
    truncated: Boolean(body.truncated),
    byteSize: typeof body.byte_size === 'number' ? body.byte_size : null,
  };
}

export async function restoreManagedFileVersion(params: {
  rootTaskId: string;
  canonicalPath: string;
  restoresChangeId: string;
  agentTaskId?: string;
}): Promise<RestoreManagedFileVersionResult> {
  try {
    const body = await request<Record<string, unknown>>('POST', '/api/v1/agent-tasks/managed-file-history/restore', {
      root_task_id: params.rootTaskId,
      canonical_path: params.canonicalPath,
      restores_change_id: params.restoresChangeId,
      agent_task_id: params.agentTaskId,
    });
    return {
      success: true,
      changeId: body.change_id as string | undefined,
      canonicalPath: body.canonical_path as string | undefined,
      restoredFromChangeId: body.restored_from_change_id as string | undefined,
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Restore failed.',
    };
  }
}
