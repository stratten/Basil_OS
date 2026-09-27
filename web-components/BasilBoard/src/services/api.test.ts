import { beforeEach, describe, expect, it, vi } from 'vitest';

const agentTaskApiMocks = vi.hoisted(() => ({
  setBaseUrl: vi.fn(),
}));
vi.mock('@agent-task/services/api', () => agentTaskApiMocks);

import { configureApiBaseUrl, getApiBaseUrl } from './api';

describe('configureApiBaseUrl', () => {
  beforeEach(() => {
    agentTaskApiMocks.setBaseUrl.mockReset();
  });

  it('configures the shared artifact revision client with the Board host port', () => {
    configureApiBaseUrl('http://127.0.0.1:9123/');

    expect(getApiBaseUrl()).toBe('http://127.0.0.1:9123');
    expect(agentTaskApiMocks.setBaseUrl).toHaveBeenCalledWith(9123);
  });
});
