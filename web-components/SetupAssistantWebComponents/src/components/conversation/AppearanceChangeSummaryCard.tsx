import type { SetupAppearanceChangeSummary } from '@/types'

interface Props {
  summary: SetupAppearanceChangeSummary
}

export function AppearanceChangeSummaryCard({ summary }: Props) {
  return (
    <div className="appearance-change-summary" aria-label="Appearance change summary">
      <ul className="appearance-change-rows">
        {summary.rows.map(row => (
          <li className="appearance-change-row" key={row.label}>
            <span className="appearance-change-label">{row.label}</span>
            {row.kind === 'color' ? (
              <span className="appearance-change-values">
                <span
                  className="appearance-change-swatch"
                  style={{ backgroundColor: row.oldColor }}
                  aria-label={`Previous ${row.label} color: ${row.oldColor}`}
                  title={`Previous ${row.label} color: ${row.oldColor}`}
                />
                <span className="appearance-change-arrow" aria-hidden="true">&rarr;</span>
                <span
                  className="appearance-change-swatch"
                  style={{ backgroundColor: row.newColor }}
                  aria-label={`New ${row.label} color: ${row.newColor}`}
                  title={`New ${row.label} color: ${row.newColor}`}
                />
              </span>
            ) : (
              <span className="appearance-change-values">
                <span className="appearance-change-font-name">{row.oldFont}</span>
                <span className="appearance-change-arrow" aria-hidden="true">&rarr;</span>
                <span className="appearance-change-font-name">{row.newFont}</span>
              </span>
            )}
          </li>
        ))}
      </ul>
      {summary.contrastWarning && (
        <p className="appearance-change-contrast-warning" role="alert">
          Contrast ratio {summary.contrastWarning.ratio.toFixed(1)}:1, below the recommended{' '}
          {summary.contrastWarning.requiredRatio}:1 for normal text — saved as requested.
        </p>
      )}
    </div>
  )
}
