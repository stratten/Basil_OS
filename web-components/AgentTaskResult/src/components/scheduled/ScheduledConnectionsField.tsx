import IconChipList, { type IconChipEntry } from '@shared/IconChipList';
import { ConnectionGlyph } from '@shared/attachmentGlyphs';
import { connectionIconSources } from '@shared/connectionIcons';
import type { ScheduleConnection } from '../../services/api';
import Dropdown, { type DropdownOption } from '../Dropdown';
import ScheduledField from './ScheduledField';

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

const PLUG_GLYPH_SIZE = 12;

// The tagged connections as icon chips, in the order saved. Each chip carries the icon its server advertises, then the bundled icon for a connection Basil knows, then a plug glyph. A problem with a connection is a separate warning-toned note after its name, so the name stays the one the person chose. A tagged id that no longer exists stays as a "Removed connection" chip so it can be untagged. Until the connection list has loaded (or when it could not be loaded) chips carry a neutral name rather than a guess, and keep their ids so nothing is dropped.
export function connectionChipEntries(connections: ScheduleConnection[], selectedIds: string[], loaded: boolean): IconChipEntry[] {
  const known = new Map(connections.map(connection => [connection.id, connection]));
  return selectedIds.map(id => {
    if (!loaded) {
      return { key: `connection:${id}`, name: 'Connection', title: 'The connection name is still loading', removeLabel: 'Stop using this connection', fallbackIcon: <ConnectionGlyph size={PLUG_GLYPH_SIZE} />, tile: true, kind: 'connection' };
    }
    const connection = known.get(id);
    const baseName = connection ? connection.friendly_name : 'Removed connection';
    return {
      key: `connection:${id}`,
      name: baseName,
      note: connectionProblem(connection) ?? undefined,
      title: connection?.description || baseName,
      removeLabel: `Stop using ${baseName}`,
      iconSources: connection ? connectionIconSources(connection.server_url, connection.server_icon_data_url) : [],
      fallbackIcon: <ConnectionGlyph size={PLUG_GLYPH_SIZE} />,
      tile: true,
      kind: 'connection',
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

// The "Connections" row of the create and edit forms. Choosing a connection tags it and it appears as a chip below the picker; the chip's remove button untags it. A tagged connection grants nothing: each tool's approval policy still applies. The row is hidden when there is nothing to show or choose.
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
    <ScheduledField label={CONNECTIONS_LABEL} help={CONNECTIONS_HELP}>
      {canPick && (
        <div className="scheduled-field__limit" title={CONNECTIONS_HELP}>
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
      <IconChipList
        groupLabel={CONNECTIONS_LABEL}
        entries={connectionChipEntries(connections, selectedIds, loaded)}
        removeDisabled={disabled}
        onRemove={(_entry, index) => onChange(selectedIds.filter((_, position) => position !== index))}
      />
    </ScheduledField>
  );
}

interface DisplayProps {
  connections: ScheduleConnection[];
  selectedIds: string[];
  loaded: boolean;
}

// Read-only chips for the connections a schedule is tied to, for the detail view. Renders nothing when none are tagged.
export function ScheduledConnectionsDisplay({ connections, selectedIds, loaded }: DisplayProps) {
  return <IconChipList groupLabel={CONNECTIONS_LABEL} entries={connectionChipEntries(connections, selectedIds, loaded)} />;
}
