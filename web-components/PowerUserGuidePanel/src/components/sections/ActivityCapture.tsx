import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function ActivityCapture() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="activityCapture"
        title="Activity Capture"
        subtitle="Automatic productivity monitoring that builds a searchable timeline of your work — never lose track of what you were doing"
      />

      <SectionGroup title="Your automatic work timeline">
        <Bullet>Takes periodic screenshots of your active window (every 30 seconds to 24 hours)</Bullet>
        <Bullet>Extracts all visible text using OCR technology</Bullet>
        <Bullet>Records app names, window titles, and timestamps</Bullet>
        <Bullet>Builds a searchable database of your work activities</Bullet>
        <Bullet>Runs quietly in the background — no interruptions</Bullet>
      </SectionGroup>

      <SectionGroup title="Your data stays private">
        <Bullet>Activity data never leaves your Mac permanently — even when using cloud AI</Bullet>
        <Bullet>Screenshots are processed locally with OCR</Bullet>
        <Bullet>You control capture frequency and can pause anytime</Bullet>
        <Bullet>Delete your activity history whenever you want</Bullet>
      </SectionGroup>

      <SectionGroup title="Never lose your work again">
        <Bullet>Searchable timeline of all your work activities</Bullet>
        <Bullet>Recreate context: "What was I working on yesterday afternoon?"</Bullet>
        <Bullet>Track productivity: See how you actually spend your time</Bullet>
        <Bullet>Automatic backup: Your work context is always preserved</Bullet>
      </SectionGroup>

      <SectionGroup title="Flexible configuration">
        <Bullet>Frequency: Every 30 seconds to once per day (Settings → Activity Capture)</Bullet>
        <Bullet>Processing: Choose local models for privacy or cloud models for enhanced analysis</Bullet>
        <Bullet>Status: See capture status in your menu bar</Bullet>
        <Bullet>History: Browse and search captures in Settings → Activity History</Bullet>
      </SectionGroup>

      <SectionGroup title="Query your work history">
        <Bullet>Browse your timeline in Settings → Activity History</Bullet>
        <Bullet>Ask about recent work: "What did I work on last Tuesday?"</Bullet>
        <Bullet>Search by app or window title for specific activities</Bullet>
        <Bullet>Note: Advanced semantic search is actively being refined</Bullet>
      </SectionGroup>

      <SectionGroup title="Getting started">
        <Bullet>Start with longer intervals (15-30 minutes) to see how it works</Bullet>
        <Bullet>Try querying your data after a day or two of captures</Bullet>
        <Bullet>Adjust frequency based on your comfort and needs</Bullet>
        <Bullet>Remember: you can pause, adjust, or delete data anytime</Bullet>
      </SectionGroup>
    </div>
  )
}
