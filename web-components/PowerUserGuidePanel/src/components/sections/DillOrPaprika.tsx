import { SectionGroup, SectionHeader } from '../Bullet'
import { GuideIcon } from '../GuideIcon'

interface HelperCardProps {
  icon: 'dill' | 'paprika'
  name: string
  hotkey: string
  role: string
  reachFor: string[]
}

const helperCards: HelperCardProps[] = [
  {
    icon: 'dill',
    name: 'Dill',
    hotkey: '⌥⌥',
    role: 'Writes the text you need, right where you are.',
    reachFor: [
      'Replying to the email or message in front of you',
      'Rewriting, shortening, or changing the tone of text you highlight',
      'Summarizing or translating what is on your screen',
    ],
  },
  {
    icon: 'paprika',
    name: 'Paprika',
    hotkey: '⌥Space',
    role: 'Works through bigger tasks and shows its progress.',
    reachFor: [
      'Researching a question across sources',
      'Multi-step work that needs tools or a plan',
      'Working with files and folders you drag in',
    ],
  },
]

const comparisonRows: Array<{ aspect: string; dill: string; paprika: string }> = [
  { aspect: 'Hotkey', dill: '⌥⌥', paprika: '⌥Space' },
  { aspect: 'Result', dill: 'Pasted into your app or shown to copy, based on your Paste output setting', paprika: 'Live panel with progress and follow-ups' },
  { aspect: 'Scope', dill: 'One request, one piece of text', paprika: 'Multi-step: research, tools, and plans' },
  { aspect: 'Extra context', dill: 'Your screen, plus any text you highlight', paprika: 'Your screen, plus files and folders you drag in' },
  { aspect: 'Back-and-forth', dill: 'Refine the draft with another request', paprika: 'Asks a quick question when unclear, then continues' },
  { aspect: 'Best for', dill: 'Writing and editing', paprika: 'Research and getting things done' },
]

function HelperCard({ icon, name, hotkey, role, reachFor }: HelperCardProps) {
  return (
    <div className="pug-model-card pug-helper-card">
      <div className="pug-model-card-header">
        <GuideIcon name={icon} size={22} />
        <h3>{name}</h3>
        <kbd className="pug-helper-hotkey">{hotkey}</kbd>
      </div>
      <p className="pug-helper-role">{role}</p>
      <div className="pug-helper-reach-label">Reach for it when</div>
      <div className="pug-model-card-bullets">
        {reachFor.map(item => (
          <div className="pug-model-card-bullet" key={item}>
            <span className="pug-model-card-dot" aria-hidden="true" />
            <span>{item}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function DillOrPaprika() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="dillAndPaprika"
        title="Dill or Paprika?"
        subtitle="Both read what's on your screen. Dill writes text you can use right away; Paprika works through bigger tasks step by step and shows results in its own panel."
      />

      <div className="pug-model-grid">
        {helperCards.map(card => <HelperCard key={card.name} {...card} />)}
      </div>

      <SectionGroup title="Side by side">
        <div className="pug-table pug-table--comparison" role="table" aria-label="Dill and Paprika comparison">
          <div className="pug-table-row pug-table-header" role="row">
            <div className="pug-table-cell pug-table-cell-label" role="columnheader" />
            <div className="pug-table-cell pug-table-cell-heading" role="columnheader">
              <span className="pug-table-heading-with-icon"><GuideIcon name="dill" size={16} />Dill</span>
            </div>
            <div className="pug-table-cell pug-table-cell-heading" role="columnheader">
              <span className="pug-table-heading-with-icon"><GuideIcon name="paprika" size={16} />Paprika</span>
            </div>
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

      <div className="pug-privacy-note pug-helper-tip">
        <GuideIcon name="dillAndPaprika" size={18} />
        <span><strong>Not sure?</strong> Start with Dill for anything you'd otherwise type yourself. Use Paprika when you'd otherwise open several apps or tabs.</span>
      </div>
    </div>
  )
}
