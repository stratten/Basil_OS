import { useState } from 'react'

const explanationItems = [
  {
    icon: '↓',
    title: 'Local models',
    detail: 'These models are stored on your Mac so supported Basil features can work privately, including when you are offline.',
  },
  {
    icon: '◉',
    title: 'Downloading in the background',
    detail: 'You can keep working or continue setup while Basil downloads and prepares these models.',
  },
]

interface Props {
  onSizeChanged: () => void
}

export default function ExplanationTray({ onSizeChanged }: Props) {
  const [isOpen, setIsOpen] = useState(false)

  return (
    <section className="explanation-tray">
      <button
        type="button"
        className="explanation-toggle"
        aria-expanded={isOpen}
        onClick={() => {
          setIsOpen(open => !open)
          requestAnimationFrame(onSizeChanged)
        }}
      >
        What are these? <span aria-hidden="true">{isOpen ? '⌃' : '⌄'}</span>
      </button>
      {isOpen && (
        <div className="explanation-content basil-presence-enter">
          {explanationItems.map(item => (
            <div className="explanation-item" key={item.title}>
              <span className="explanation-icon" aria-hidden="true">{item.icon}</span>
              <div>
                <div className="explanation-title">{item.title}</div>
                <div className="explanation-detail">{item.detail}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
