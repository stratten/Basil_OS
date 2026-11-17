import type { ReactNode } from 'react';
import type { ScheduledAgentTask } from '../../types';
import type { ReasoningModel, ScheduleConnection } from '../../services/api';
import { CONNECTIONS_LABEL, ScheduledConnectionsDisplay } from './ScheduledConnectionsField';
import { describeScheduledModel } from './ScheduledModelField';
import { describeChain, describeExclusionWindows, exclusionWindowsFromConfig } from './scheduledChainHelpers';
import { formatTimestamp12h, summarizeSchedule } from './scheduledAgentTaskHelpers';

function MetaRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="scheduled-meta__row">
      <span className="scheduled-meta__label">{label}</span>
      <div>{children}</div>
    </div>
  );
}

interface Props {
  item: ScheduledAgentTask;
  models: ReasoningModel[];
  connections: ScheduleConnection[];
  connectionsLoaded: boolean;
}

// The read view's labeled facts: schedule, model, quiet hours, runs, next run and connections. A row appears only when the schedule has something to say for it.
export default function ScheduledMeta({ item, models, connections, connectionsLoaded }: Props) {
  const windows = exclusionWindowsFromConfig(item.schedule_config);
  const connectionIds = item.connection_ids ?? [];
  return (
    <div className="scheduled-meta">
      <MetaRow label="Schedule">{summarizeSchedule(item)}</MetaRow>
      <MetaRow label="Model">{describeScheduledModel(models, item.model_id)}</MetaRow>
      {windows.length > 0 && <MetaRow label="Quiet hours">{describeExclusionWindows(windows)}</MetaRow>}
      {item.chain_config?.mode === 'chained' && <MetaRow label="Runs">{describeChain(item.chain_config)}</MetaRow>}
      {item.next_run_at && <MetaRow label="Next run">{formatTimestamp12h(item.next_run_at)}</MetaRow>}
      {connectionIds.length > 0 && (
        <MetaRow label={CONNECTIONS_LABEL}>
          <ScheduledConnectionsDisplay connections={connections} selectedIds={connectionIds} loaded={connectionsLoaded} />
        </MetaRow>
      )}
    </div>
  );
}
