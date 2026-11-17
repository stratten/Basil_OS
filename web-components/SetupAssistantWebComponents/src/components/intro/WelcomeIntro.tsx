import { SetupPathChooser } from './SetupPathChooser'
import type { ComfortLevel } from '@/components/express/expressTypes'

interface Props {
  onChooseManual: () => void
  onChooseSelf: (comfort: ComfortLevel) => void
  onChooseYolo: () => void
}

export function WelcomeIntro({ onChooseManual, onChooseSelf, onChooseYolo }: Props) {
  return (
    <section className="phase-section welcome-intro">
      <img className="welcome-intro-logo" src="/images/basil-logo.png" alt="" aria-hidden="true" />
      <p className="eyebrow">Setup assistant</p>
      <h2>Meet <span className="gradient-name">Basil</span>.</h2>
      <div className="welcome-intro-copy">
        <p>
          I'm an assistant for whatever you're working on, from a quick answer or a rewrite to a longer task you'd rather hand off. When it helps, I can see what's on your screen so my help fits what you're doing.
        </p>
      </div>
      <details className="welcome-intro-privacy">
        <summary>What stays on this Mac</summary>
        <p>
          Everything I store, such as your conversations, notes, recordings, and settings, lives in the hidden <code>.basil</code> folder in your home folder. If you choose a cloud model, only the requests sent to it leave this Mac, and they go to that provider. The download also includes an Uninstall Basil script that removes all of it.
        </p>
      </details>
      <p className="welcome-intro-lead">Choose how you'd like to set up.</p>
      <SetupPathChooser onChooseManual={onChooseManual} onChooseSelf={onChooseSelf} onChooseYolo={onChooseYolo} />
    </section>
  )
}
