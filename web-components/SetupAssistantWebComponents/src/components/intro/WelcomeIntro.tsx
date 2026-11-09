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
          I'm an assistant that can help with anything you're working on. I'm "context-aware" —
          which just means that, when it's useful, I can see what's on your screen or pull in
          information so the work we do together fits what you actually need. Sometimes that's a
          quick answer or a sentence rewrite. Sometimes it's drafting something with you.
          Sometimes it's a longer task you'd rather hand off entirely.
        </p>
        <p>
          Next you choose how to set up. Going step by step is what I recommend: a few short
          preference steps, then an optional guided conversation where I help you set things up.
          If you'd rather I did the work, I can set up this Mac based on how comfortable you are,
          and you see the full list before anything changes.
        </p>
      </div>
      <p className="welcome-intro-privacy">
        <strong>What stays on this Mac:</strong> everything I store, such as your conversations,
        notes, recordings, and settings, lives in the hidden <code>.basil</code> folder in your
        home folder. If you choose a cloud model, only the requests sent to it leave this Mac, and
        they go to that provider. The download also includes an Uninstall Basil script that removes
        all of it.
      </p>
      <SetupPathChooser onChooseManual={onChooseManual} onChooseSelf={onChooseSelf} onChooseYolo={onChooseYolo} />
    </section>
  )
}
