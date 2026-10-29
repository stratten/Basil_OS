import AttachmentList from '@shared/AttachmentList';
import type { AttachmentEntry } from '@shared/attachmentPaths';
import type { ScheduleConnection } from '../../services/api';
import Dropdown, { type DropdownOption } from '../Dropdown';

const RECONNECT_STATUSES = new Set(['needs_reconnect', 'token_unavailable']);

// What is wrong with a tagged connection right now, in words a person can act on, or null when it can be used. Mirrors the checks a run makes before it starts, so the schedule warns about a problem before the run fails with it.
export function connectionProblem(connection: ScheduleConnection | undefined): string | null {
  if (!connection) return 'removed';
  if (!connection.enabled) return 'switched off';
  if (RECONNECT_STATUSES.has(connection.last_connection_status ?? '')) return 'needs signing in again';
  return null;
}

// Whether the edited selection differs from what is saved, ignoring order. Absent saved ids count as none.
export function connectionsChanged(edited: string[], saved: string[] | undefined): boolean {
  const before = new Set(saved ?? []);
  const after = new Set(edited);
  return before.size !== after.size || [...after].some(id => !before.has(id));
}

// The tagged connections as chip rows, in the order saved, drawn with the same chip style as the reference files. A tagged id that no longer exists stays as a "Removed connection" row so it can be untagged. Until the connection list has loaded (or when it could not be loaded) rows carry a neutral name rather than a guess, and keep their ids so nothing is dropped.
export function connectionEntries(connections: ScheduleConnection[], selectedIds: string[], loaded: boolean): AttachmentEntry[] {
  const known = new Map(connections.map(connection => [connection.id, connection]));
  return selectedIds.map(id => {
    if (!loaded) {
      return { key: `connection:${id}`, path: id, kind: 'connection' as const, name: 'Connection', title: 'The connection name is still loading', removeLabel: 'Stop using this connection' };
    }
    const connection = known.get(id);
    const baseName = connection ? connection.friendly_name : 'Removed connection';
    const problem = connectionProblem(connection);
    return {
      key: `connection:${id}`,
      path: id,
      kind: 'connection' as const,
      name: problem ? `${baseName} (${problem})` : baseName,
      title: connection?.description || baseName,
      removeLabel: `Stop using ${baseName}`,
    };
  });
}

export const CONNECTIONS_LABEL = 'Connections';

const CONNECTIONS_HELP = 'Every run of this scheduled task is told to use exactly these connections. Each tool still asks for approval the way it does in Settings.';

interface FieldProps {
  connections: ScheduleConnection[];
  selectedIds: string[];
  onChange: (next: string[]) => void;
  // False until the connection list has loaded, or when it could not be loaded. The picker stays hidden then, so a failed load is never shown as there being nothing to choose.
  loaded: boolean;
  disabled?: boolean;
}

// The "Connections" row of the create and edit forms, laid out like the Model row. Choosing a connection tags it and it appears as a chip below the picker; the chip's remove button untags it. A tagged connection grants nothing: each tool's approval policy still applies. The row is hidden when there is nothing to show or choose.
export default function ScheduledConnectionsField({ connections, selectedIds, onChange, loaded, disabled }: FieldProps) {
  const available = connections.filter(connection => !selectedIds.includes(connection.id));
  const canPick = loaded && available.length > 0;
  if (!canPick && selectedIds.length === 0) return null;
  // The shared Dropdown, not a native select: a native select draws the macOS system pill and popup, which matches nothing else in the widget.
  const options: DropdownOption<string>[] = available.map(connection => ({
    value: connection.id,
    label: connection.friendly_name,
    hint: connectionProblem(connection) ?? undefined,
  }));
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 8,
        fontFamily: 'var(--font-family-light)',
        fontSize: 'var(--font-size-callout)',
        color: 'var(--text-secondary)',
      }}
    >
      <span style={{ fontFamily: 'var(--font-family-medium)', color: 'var(--text-tertiary)', minWidth: 72, paddingTop: 4 }} title={CONNECTIONS_HELP}>
        {CONNECTIONS_LABEL}
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1, minWidth: 0 }}>
        {canPick && (
          <div style={{ maxWidth: 240 }} title={CONNECTIONS_HELP}>
            <Dropdown
              value=""
              options={options}
              placeholder="Add a connection…"
              ariaLabel="Add a connection"
              disabled={disabled}
              onChange={(id) => {
                if (id) onChange([...selectedIds, id]);
              }}
            />
          </div>
        )}
        <AttachmentList
          className="attachment-list--inset"
          groupLabel={CONNECTIONS_LABEL}
          showHeading={false}
          entries={connectionEntries(connections, selectedIds, loaded)}
          removeDisabled={disabled}
          onRemove={(entry) => onChange(selectedIds.filter(id => id !== entry.path))}
        />
      </div>
    </div>
  );
}

interface DisplayProps {
  connections: ScheduleConnection[];
  selectedIds: string[];
  loaded: boolean;
}

// Read-only chips for the connections a schedule is tied to, for the detail view. Renders nothing when none are tagged.
export function ScheduledConnectionsDisplay({ connections, selectedIds, loaded }: DisplayProps) {
  return (
    <AttachmentList
      className="attachment-list--inset"
      groupLabel={CONNECTIONS_LABEL}
      showHeading={false}
      entries={connectionEntries(connections, selectedIds, loaded)}
    />
  );
}
