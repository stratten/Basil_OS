interface Props {
  onContinue: () => void
}

export function WelcomeIntro({ onContinue }: Props) {
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
          Next come three short preference steps. After that is an optional guided
          conversation where I help you set things up. You can stop it any time.
        </p>
      </div>
      <p className="welcome-intro-privacy">
        <strong>What stays on this Mac:</strong> everything I store, such as your conversations,
        notes, recordings, and settings, lives in the hidden <code>.basil</code> folder in your
        home folder. If you choose a cloud model, only the requests sent to it leave this Mac, and
        they go to that provider. The download also includes an Uninstall Basil script that removes
        all of it.
      </p>
      <button type="button" className="primary-button welcome-intro-primary" onClick={onContinue}>
        Start setup
      </button>
    </section>
  )
}
