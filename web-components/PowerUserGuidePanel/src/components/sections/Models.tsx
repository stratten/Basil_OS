import type { ReactNode } from 'react'
import { GuideIcon, type GuideIconName } from '../GuideIcon'
import { SectionHeader } from '../Bullet'

interface ModelCardProps {
  icon: GuideIconName
  title: string
  bullets: string[]
  isSecondary?: boolean
}

function ModelCard({ icon, title, bullets, isSecondary = false }: ModelCardProps) {
  return (
    <div className={`pug-model-card${isSecondary ? ' pug-model-card--secondary' : ''}`}>
      <div className="pug-model-card-header">
        <GuideIcon name={icon} size={18} className="pug-model-card-icon" />
        <h3>{title}</h3>
      </div>
      <div className="pug-model-card-bullets">
        {bullets.map(bullet => (
          <div className="pug-model-card-bullet" key={bullet}>
            <span className="pug-model-card-dot" aria-hidden="true" />
            <span>{bullet}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function PrivacyNote({ children }: { children: ReactNode }) {
  return (
    <div className="pug-privacy-note">
      <GuideIcon name="privacy" size={16} className="pug-privacy-note-icon" />
      <span>{children}</span>
    </div>
  )
}

export default function Models() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="models"
        title="Models"
        subtitle="Basil can think locally on your Mac or use faster cloud models. The choice mostly comes down to privacy, speed, and cost."
      />

      <div className="pug-model-grid">
        <ModelCard
          icon="speechToText"
          title="Speech-to-text"
          bullets={[
            'Small local models start quickly and work well for casual dictation.',
            'Larger local models handle noisy rooms, accents, and important text better.',
            'You can switch later; this choice is not permanent.',
          ]}
        />
        <ModelCard
          icon="thinkingModels"
          title="Thinking models"
          bullets={[
            'Local models are free, private, offline, and run on your Mac.',
            'Cloud models are faster and better at hard requests, but each request costs money.',
            'Basil does not track or store request contents.',
          ]}
        />
      </div>

      <div className="pug-model-grid">
        <ModelCard
          icon="cloudPricing"
          title="Cloud pricing"
          bullets={[
            'Basil Cloud requires a Basil account with a payment method before usage.',
            'Model providers charge Basil for cloud requests; Basil passes that cost through with a small markup.',
            'If you bring your own provider account, that provider bills you directly.',
          ]}
        />
        <ModelCard
          icon="advancedOptions"
          title="Advanced options"
          isSecondary
          bullets={[
            'Download GGUF models from HuggingFace by pasting a repo link.',
            'Use existing models from disk, LM Studio, or Ollama.',
            'Connect OpenAI-, Anthropic-, or Gemini-compatible providers from Settings.',
          ]}
        />
      </div>

      <PrivacyNote>
        Privacy note: local models stay on your Mac. Cloud requests are sent only to the model provider needed to
        answer.
      </PrivacyNote>
    </div>
  )
}
