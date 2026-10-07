import { describe, expect, it } from 'vitest';
import { backendStatusToAgentStatus, isInFlightAgentStatus } from './agentHydration';
import { mapBackendStatus } from '../components/sidebar/sidebarUtils';
import { isActiveStatus } from '../components/sidebar/sidebarItemBuilders';

describe('paused status mapping', () => {
  it('maps the backend paused status to the local paused status', () => {
    expect(backendStatusToAgentStatus('paused')).toBe('paused');
    expect(mapBackendStatus('paused')).toBe('paused');
  });

  it('treats a paused task as active but not in flight', () => {
    expect(isActiveStatus('paused')).toBe(true);
    expect(isInFlightAgentStatus('paused')).toBe(false);
  });
});
