import type { SectionId } from '../types'
import { GuideIcon, type GuideIconName } from './GuideIcon'

interface SidebarSection {
  id: SectionId
  label: string
  icon: GuideIconName
  isSubItem?: boolean
}

const sections: SidebarSection[] = [
  { id: 'transcription', label: 'Transcription', icon: 'transcription' },
  { id: 'assistantSession', label: 'Dill', icon: 'dill' },
  { id: 'agentTasks', label: 'Paprika', icon: 'paprika' },
  { id: 'dillOrPaprika', label: 'Dill or Paprika?', icon: 'dillAndPaprika', isSubItem: true },
  { id: 'conversation', label: 'Conversation', icon: 'conversation' },
  { id: 'activityCapture', label: 'Activity Capture', icon: 'activityCapture' },
  { id: 'models', label: 'Models', icon: 'models' },
]

interface SidebarProps {
  selected: SectionId
  onSelect: (id: SectionId) => void
}

export default function Sidebar({ selected, onSelect }: SidebarProps) {
  return (
    <nav className="pug-sidebar" aria-label="Power User Guide sections">
      {sections.map(section => {
        const isSelected = section.id === selected
        return (
          <button
            key={section.id}
            type="button"
            className={`pug-sidebar-row${section.isSubItem ? ' pug-sidebar-row--sub' : ''}${isSelected ? ' pug-sidebar-row--selected' : ''}`}
            onClick={() => onSelect(section.id)}
            aria-current={isSelected}
          >
            <GuideIcon name={section.icon} size={18} className="pug-sidebar-icon" />
            <span>{section.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
