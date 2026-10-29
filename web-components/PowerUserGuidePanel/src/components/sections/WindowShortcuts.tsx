import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function WindowShortcuts() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="shortcuts"
        title="Window shortcuts"
        subtitle="Two keyboard shortcuts work inside Basil's windows, so you can keep them out of the way and send messages without reaching for the mouse."
      />

      <SectionGroup title="Collapse and expand">
        <Bullet><kbd className="pug-hotkey">⌘E</kbd> collapses a Basil window so only its title bar remains, and expands it again</Bullet>
        <Bullet>It works in Home, Dill, Paprika, Meeting Assistant, Ambient Suggestions, Skill Reconciliation, and the setup window</Bullet>
        <Bullet>Collapsing does not close the window, so it is one keypress away whenever you want it back</Bullet>
        <Bullet>The collapse button in a window's title bar shows the shortcut when you hover over it</Bullet>
      </SectionGroup>

      <SectionGroup title="Send a message">
        <Bullet><kbd className="pug-hotkey">⌘↵</kbd> (Command-Return) sends your message from Basil's message boxes</Bullet>
        <Bullet>You can keep your hands on the keyboard from the first word to sending</Bullet>
      </SectionGroup>
    </div>
  )
}
