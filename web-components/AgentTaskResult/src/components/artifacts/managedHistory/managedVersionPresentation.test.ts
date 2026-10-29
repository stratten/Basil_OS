import { describe, expect, it } from 'vitest';
import type { AgentTaskRunFocusSummary } from '../../run/agentTaskRunFocus';
import type { ManagedFileVersion } from './managedHistoryApi';
import { managedVersionLabel } from './managedVersionPresentation';

function version(agentTaskId: string): ManagedFileVersion {
  return { agentTaskId, operation: 'edit', createdAt: '2026-08-10T12:00:00Z' } as unknown as ManagedFileVersion;
}

function run(id: string, displayNumber: string): AgentTaskRunFocusSummary {
  return { id, displayNumber } as unknown as AgentTaskRunFocusSummary;
}

describe('managedVersionLabel', () => {
  it('labels the newest version Current', () => {
    expect(managedVersionLabel([version('a'), version('b')], 0, undefined)).toBe('Current');
  });

  it('uses the display number of the run that produced an older version', () => {
    const label = managedVersionLabel([version('c'), version('b')], 1, [run('b', '1.1')]);
    expect(label.startsWith('Run 1.1 · edit · ')).toBe(true);
  });

  it('falls back to a position-based number when the run is unknown', () => {
    const label = managedVersionLabel([version('c'), version('b'), version('a')], 1, [run('zzz', '9')]);
    expect(label.startsWith('Run 2 · edit · ')).toBe(true);
  });
});
