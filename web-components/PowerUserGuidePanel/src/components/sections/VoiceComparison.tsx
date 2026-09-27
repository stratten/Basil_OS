import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

const comparisonRows: Array<{ aspect: string; dill: string; paprika: string }> = [
  { aspect: 'Output', dill: 'Instant paste', paprika: 'Panel with options' },
  { aspect: 'Context', dill: 'Auto screen reading', paprika: 'Manual if needed' },
  { aspect: 'Complexity', dill: 'Single-shot', paprika: 'Multi-step' },
  { aspect: 'Best for', dill: 'Content creation', paprika: 'Research & planning' },
]

export default function VoiceComparison() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="🔁"
        title="Dill vs Paprika"
        subtitle="Two powerful voice features — here's how to choose the right one"
      />

      <SectionGroup title="Dill">
        <Bullet>Quick, single-shot text generation</Bullet>
        <Bullet>Automatically reads your screen for context</Bullet>
        <Bullet>Perfect for drafts, replies, and summaries</Bullet>
        <Bullet>Results paste directly into your active window</Bullet>
        <Bullet>No selection required — just speak your request</Bullet>
      </SectionGroup>

      <SectionGroup title="Paprika">
        <Bullet>Multi-step agentic workflows</Bullet>
        <Bullet>Can perform research and use tools</Bullet>
        <Bullet>Perfect for complex analysis and planning</Bullet>
        <Bullet>Results appear in a dedicated panel</Bullet>
        <Bullet>Can break down big tasks into clear action plans</Bullet>
      </SectionGroup>

      <SectionGroup title="Use Dill when:">
        <Bullet>You need to draft a quick reply or summary</Bullet>
        <Bullet>You want immediate paste to your current app</Bullet>
        <Bullet>You're working with visible content on screen</Bullet>
        <Bullet>The task is straightforward and content-focused</Bullet>
      </SectionGroup>

      <SectionGroup title="Use Paprika when:">
        <Bullet>You need research or information gathering</Bullet>
        <Bullet>The task requires multiple steps or tool use</Bullet>
        <Bullet>You want to review and edit before using the result</Bullet>
        <Bullet>You're doing analysis, planning, or strategy work</Bullet>
      </SectionGroup>

      <SectionGroup title="Quick comparison">
        <div className="pug-table" role="table" aria-label="Dill versus Paprika comparison">
          <div className="pug-table-row pug-table-header" role="row">
            <div className="pug-table-cell pug-table-cell-label" role="columnheader" />
            <div className="pug-table-cell pug-table-cell-heading" role="columnheader">Dill</div>
            <div className="pug-table-cell pug-table-cell-heading" role="columnheader">Paprika</div>
          </div>
          {comparisonRows.map(row => (
            <div className="pug-table-row" role="row" key={row.aspect}>
              <div className="pug-table-cell pug-table-cell-label" role="rowheader">{row.aspect}</div>
              <div className="pug-table-cell" role="cell">{row.dill}</div>
              <div className="pug-table-cell" role="cell">{row.paprika}</div>
            </div>
          ))}
        </div>
      </SectionGroup>
    </div>
  )
}
