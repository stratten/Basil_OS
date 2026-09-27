import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function Transcription() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="🎙️"
        title="Voice Transcription"
        subtitle="Transform your voice into text instantly, anywhere on your Mac"
      />

      <SectionGroup title="Here's how it works">
        <Bullet>Press your transcription hotkey to start recording your voice</Bullet>
        <Bullet>Speak naturally — say whatever you want to type</Bullet>
        <Bullet>Press the same key again when you're done</Bullet>
        <Bullet>Your words appear as text in a handy little window</Bullet>
        <Bullet>Click to copy it, or let Basil paste it automatically</Bullet>
      </SectionGroup>

      <SectionGroup title="Why we need microphone access" badge="Required">
        <Bullet>Your voice stays private — everything happens on your Mac</Bullet>
        <Bullet>We can't transcribe without hearing you speak</Bullet>
        <Bullet>You control exactly when recording starts and stops</Bullet>
      </SectionGroup>

      <SectionGroup title="Choosing your transcription model">
        <Bullet>Faster models: Great for quick notes and casual use</Bullet>
        <Bullet>Larger models: Better accuracy for important documents</Bullet>
        <Bullet>Don't worry — you can always change this later</Bullet>
      </SectionGroup>

      <SectionGroup title="Getting the best results">
        <Bullet>Find a quiet spot when possible</Bullet>
        <Bullet>Speak at your normal pace — no need to talk slowly</Bullet>
        <Bullet>Turn on auto-paste in Settings to save clicks</Bullet>
      </SectionGroup>

      <SectionGroup title="About the hotkey">
        <Bullet>Default hotkey: ⌘+⌘ (double-tap Command, hold to record)</Bullet>
        <Bullet>Push-to-talk: hold after double-tap, release to transcribe</Bullet>
        <Bullet>Customize anytime in Settings → Hotkeys</Bullet>
      </SectionGroup>
    </div>
  )
}
