import type { AgendaPillState } from './agendaPillState'

// What each label on the to-do list means, plus who decides the order. Collapsed by default so it adds no text until someone asks.
const LEGEND_ENTRIES: ReadonlyArray<{ state: AgendaPillState; label: string; meaning: string }> = [
  { state: 'working', label: 'Working now', meaning: 'I am busy on this one right now.' },
  { state: 'your_turn', label: 'Your turn', meaning: 'This is the one we are on, and I am waiting for you.' },
  { state: 'pending', label: 'To do', meaning: 'Not started yet.' },
  { state: 'completed', label: 'Done', meaning: 'We finished this one.' },
  { state: 'skipped', label: 'Skipped', meaning: 'You chose to leave this one out.' },
  { state: 'deferred', label: 'Later', meaning: 'Saved for another time.' },
]

export function SetupAgendaLegend() {
  return (
    <details className="setup-agenda-legend">
      <summary>What do these labels mean?</summary>
      <dl className="setup-agenda-legend-list">
        {LEGEND_ENTRIES.map(entry => (
          <div key={entry.state} className="setup-agenda-legend-row">
            <dt>
              <span className={`setup-agenda-sidebar-status-pill pill-${entry.state}`}>{entry.label}</span>
            </dt>
            <dd>{entry.meaning}</dd>
          </div>
        ))}
      </dl>
      <p className="setup-agenda-legend-note">
        I choose the order from what I learn about you, and I adjust this list as we finish things. To pick one yourself, click it and I will start it next.
      </p>
    </details>
  )
}
