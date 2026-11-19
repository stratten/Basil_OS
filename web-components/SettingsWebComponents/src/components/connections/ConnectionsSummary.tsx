import type { MCPConnection } from '../../types'

interface ConnectionsSummaryProps {
  connections: readonly MCPConnection[]
}

const ATTENTION_STATUSES = new Set(['needs_reconnect', 'token_unavailable', 'error'])

function pluralize(count: number, singular: string, plural: string): string {
  return `${count} ${count === 1 ? singular : plural}`
}

/** The connection names, with a count when two connections share a name. Names are the ones the person gave or recognizes, such as "Work inbox", not the server hostname. */
export function connectionSummaryLabels(names: readonly string[]): string[] {
  const counts = new Map<string, number>()
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1)
  return [...counts.entries()].map(([name, count]) => (count > 1 ? `${name} (${count})` : name))
}

/** One line that answers "what is connected, and is anything wrong" without scrolling through every row. */
export function ConnectionsSummary({ connections }: ConnectionsSummaryProps) {
  if (connections.length === 0) return null

  const healthy = connections.filter((connection) => connection.lastConnectionStatus === 'healthy').length
  const needAttention = connections.filter((connection) => ATTENTION_STATUSES.has(connection.lastConnectionStatus ?? '')).length
  const notChecked = connections.length - healthy - needAttention
  const names = connectionSummaryLabels(connections.map((connection) => connection.friendlyName))

  const statusParts = [
    healthy > 0 ? `${healthy} healthy` : null,
    needAttention > 0 ? `${needAttention} need${needAttention === 1 ? 's' : ''} attention` : null,
    notChecked > 0 ? `${notChecked} not checked yet` : null,
  ].filter((part): part is string => part !== null)

  return (
    <p className="connections-summary" role="status" data-needs-attention={needAttention > 0 ? 'true' : 'false'}>
      <span className="connections-summary-headline">
        {pluralize(connections.length, 'connection', 'connections')} set up: {names.join(', ')}.
      </span>{' '}
      <span className="connections-summary-status">{statusParts.join(', ')}</span>
    </p>
  )
}
