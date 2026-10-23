import type { ReactNode } from 'react'
import { GuideIcon, type GuideIconName } from './GuideIcon'

export function Bullet({ children }: { children: ReactNode }) {
  return (
    <div className="pug-bullet">
      <span className="pug-bullet-dot" aria-hidden="true">•</span>
      <span>{children}</span>
    </div>
  )
}

export function SectionGroup({ title, badge, children }: { title: string; badge?: string; children: ReactNode }) {
  return (
    <div className="pug-group">
      <div className="pug-group-title-row">
        <h2 className="pug-group-title">{title}</h2>
        {badge && <span className="pug-group-badge">{badge}</span>}
      </div>
      <div className="pug-group-body">{children}</div>
    </div>
  )
}

export function SectionHeader({ icon, title, subtitle }: { icon: GuideIconName; title: string; subtitle: string }) {
  return (
    <header className="pug-section-header">
      <div className="pug-section-header-row">
        <GuideIcon name={icon} size={26} className="pug-section-icon" />
        <h1>{title}</h1>
      </div>
      <p className="pug-section-subtitle">{subtitle}</p>
    </header>
  )
}
