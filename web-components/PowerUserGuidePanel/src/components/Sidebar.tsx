import type { SectionId } from '../types'
import paprikaIcon from '../assets/PaprikaIcon.png'

interface SidebarSection {
  id: SectionId
  label: string
  icon: string
}

const sections: SidebarSection[] = [
  { id: 'transcription', label: 'Transcription', icon: '🎙️' },
  { id: 'assistantSession', label: 'Dill', icon: '✨' },
  { id: 'agentTasks', label: 'Paprika', icon: 'paprika' },
  { id: 'voiceComparison', label: 'Voice Comparison', icon: '🔁' },
  { id: 'conversation', label: 'Conversation', icon: '💬' },
  { id: 'activityCapture', label: 'Activity Capture', icon: '📈' },
  { id: 'models', label: 'Models', icon: '💻' },
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
            className={`pug-sidebar-row${isSelected ? ' pug-sidebar-row--selected' : ''}`}
            onClick={() => onSelect(section.id)}
            aria-current={isSelected}
          >
            {section.icon === 'paprika' ? (
              <img src={paprikaIcon} alt="" className="pug-sidebar-icon-image" />
            ) : (
              <span className="pug-sidebar-icon" aria-hidden="true">{section.icon}</span>
            )}
            <span>{section.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
