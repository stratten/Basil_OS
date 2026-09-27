import { memo } from 'react'

import type {
  SetupSessionAgendaItem,
  SetupSessionAgendaItemStatus,
} from '@/state/setupAssistantStore'

// Sticky left-rail sidebar that renders the session agenda. The agenda
// is the visible spine of the setup session: the things Basil and the
// user are working through together.
//
// Two shapes, switched by `isCollapsed`:
//
//   - Expanded: title + "N of M done" subhead, then a card per agenda
//     item with a status pill and kind-keyed left-edge accent.
//   - Collapsed: a ~64px-wide rail with a circular progress ring
//     (N / M) at the top, a vertical strip of status dots in the
//     middle (one per agenda item, tooltipped with its title), and a
//     chevron-right button at the bottom to re-expand. Pure visuals;
//     no vertical-text labels.
//
// When the agenda hasn't been proposed yet (orientation phase or the
// first conversation turn before propose_session_agenda fires), the
// expanded form shows an honest empty state and the collapsed form
// shows an inert placeholder ring.

export interface SetupAgendaSidebarProps {
  items: SetupSessionAgendaItem[]
  isCollapsed: boolean
  onToggleCollapsed: (collapsed: boolean) => void
}

const STATUS_LABELS: Record<SetupSessionAgendaItemStatus, string> = {
  pending: 'To do',
  in_progress: 'Working on',
  completed: 'Done',
  skipped: 'Skipped',
  deferred: 'Later',
}

const STATUS_ORDER: Record<SetupSessionAgendaItemStatus, number> = {
  in_progress: 0,
  pending: 1,
  deferred: 2,
  completed: 3,
  skipped: 4,
}

function SetupAgendaSidebarComponent({
  items,
  isCollapsed,
  onToggleCollapsed,
}: SetupAgendaSidebarProps) {
  const hasItems = items.length > 0
  const summary = computeAgendaSummary(items)
  const sortedItems = hasItems ? sortItemsForDisplay(items) : []

  if (isCollapsed) {
    return (
      <aside
        className="setup-agenda-sidebar is-collapsed"
        aria-label="Setup agenda (collapsed)"
      >
        <CollapsedSummaryRing summary={summary} hasItems={hasItems} />
        {hasItems && (
          <ol className="setup-agenda-collapsed-dot-strip" aria-hidden="true">
            {sortedItems.map(item => (
              <li
                key={item.id}
                className={`setup-agenda-collapsed-dot state-${item.status}`}
                title={`${item.title} (${STATUS_LABELS[item.status]})`}
              />
            ))}
          </ol>
        )}
        <button
          type="button"
          className="setup-agenda-collapsed-expand"
          aria-label="Expand agenda"
          aria-expanded={false}
          aria-controls="setup-agenda-sidebar-body"
          onClick={() => onToggleCollapsed(false)}
        >
          <ChevronRightIcon />
        </button>
      </aside>
    )
  }

  return (
    <aside className="setup-agenda-sidebar" aria-label="Setup agenda">
      <header className="setup-agenda-sidebar-header">
        <div className="setup-agenda-sidebar-header-text">
          <h2 className="setup-agenda-sidebar-title">What we're covering</h2>
          {hasItems && (
            <p className="setup-agenda-sidebar-summary">
              {summary.completed} of {summary.total} done
              {summary.skipped > 0 && (
                <span className="setup-agenda-sidebar-summary-skipped">
                  , {summary.skipped} skipped
                </span>
              )}
            </p>
          )}
        </div>
        <button
          type="button"
          className="setup-agenda-sidebar-toggle"
          aria-label="Collapse agenda"
          aria-expanded={true}
          aria-controls="setup-agenda-sidebar-body"
          onClick={() => onToggleCollapsed(true)}
        >
          <ChevronLeftIcon />
        </button>
      </header>
      <div className="setup-agenda-sidebar-body" id="setup-agenda-sidebar-body">
        {!hasItems && (
          <p className="setup-agenda-sidebar-empty">
            I'll lay out what we should cover here once we get into the setup conversation.
          </p>
        )}
        {hasItems && (
          <ol className="setup-agenda-sidebar-list">
            {sortedItems.map(item => (
              <li
                key={item.id}
                className={`setup-agenda-sidebar-item state-${item.status} kind-${item.kind}`}
                data-kind={item.kind}
              >
                <div className="setup-agenda-sidebar-item-row">
                  <span
                    className={`setup-agenda-sidebar-status-pill pill-${item.status}`}
                    title={STATUS_LABELS[item.status]}
                  >
                    {STATUS_LABELS[item.status]}
                  </span>
                  <span className="setup-agenda-sidebar-item-title">{item.title}</span>
                </div>
                {item.intent && (
                  <p className="setup-agenda-sidebar-item-intent">{item.intent}</p>
                )}
              </li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  )
}

export const SetupAgendaSidebar = memo(SetupAgendaSidebarComponent)

interface AgendaSummary {
  completed: number
  total: number
  skipped: number
}

// Skipped items still count toward `total` (they remain visible in the
// agenda); they're surfaced separately as "N skipped" so the user can
// see at a glance that not everything in the denominator is still on
// the work list.
function computeAgendaSummary(items: SetupSessionAgendaItem[]): AgendaSummary {
  let completed = 0
  let skipped = 0
  for (const item of items) {
    if (item.status === 'completed') completed += 1
    else if (item.status === 'skipped') skipped += 1
  }
  return { completed, total: items.length, skipped }
}

function CollapsedSummaryRing({
  summary,
  hasItems,
}: {
  summary: AgendaSummary
  hasItems: boolean
}) {
  if (!hasItems || summary.total === 0) {
    return (
      <div
        className="setup-agenda-collapsed-ring is-empty"
        role="img"
        aria-label="Agenda has no items yet"
        title="Agenda will appear once we start the conversation"
      >
        <ProgressRing completed={0} total={0} />
      </div>
    )
  }
  const tooltipBase = `${summary.completed} of ${summary.total} done`
  const tooltip = summary.skipped > 0
    ? `${tooltipBase}, ${summary.skipped} skipped`
    : tooltipBase
  return (
    <div
      className="setup-agenda-collapsed-ring"
      role="img"
      aria-label={tooltip}
      title={tooltip}
    >
      <ProgressRing completed={summary.completed} total={summary.total} />
    </div>
  )
}

function ProgressRing({ completed, total }: { completed: number; total: number }) {
  const size = 40
  const stroke = 4
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const progress = total > 0 ? Math.min(1, completed / total) : 0
  const dashOffset = circumference * (1 - progress)

  return (
    <svg
      className="setup-agenda-progress-ring"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      aria-hidden="true"
    >
      <circle
        className="setup-agenda-progress-ring-track"
        cx={size / 2}
        cy={size / 2}
        r={radius}
        strokeWidth={stroke}
        fill="none"
      />
      {total > 0 && (
        <circle
          className="setup-agenda-progress-ring-fill"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      )}
      <text
        className="setup-agenda-progress-ring-label"
        x="50%"
        y="50%"
        textAnchor="middle"
        dominantBaseline="central"
      >
        {total > 0 ? `${completed}/${total}` : '–'}
      </text>
    </svg>
  )
}

function ChevronLeftIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M8.5 3L5 7L8.5 11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function ChevronRightIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <path
        d="M5.5 3L9 7L5.5 11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// Display order: in_progress items rise to the top, then pending, then
// deferred, then completed, then skipped. Within a status, original
// order from the agent is preserved. This keeps "what Basil is doing
// right now" visually closest to the conversation and gently buries
// resolved items at the bottom without removing them from view.
function sortItemsForDisplay(
  items: SetupSessionAgendaItem[],
): SetupSessionAgendaItem[] {
  return [...items]
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const orderDiff = STATUS_ORDER[a.item.status] - STATUS_ORDER[b.item.status]
      if (orderDiff !== 0) return orderDiff
      return a.index - b.index
    })
    .map(entry => entry.item)
}
