import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function AgentTasks() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="✅"
        title="Paprika"
        subtitle="Your personal assistant that actually gets things done — just speak and watch it happen"
      />

      <SectionGroup title="It's like having a super-smart assistant">
        <Bullet>Press your agent task hotkey (default: ⌥+Space)</Bullet>
        <Bullet>Tell it what to do: "Summarize this page" or "Write a polite decline email"</Bullet>
        <Bullet>Basil reads what's on your screen and gets to work</Bullet>
        <Bullet>Watch the results appear live in a handy little panel</Bullet>
        <Bullet>Copy, paste, or tweak — whatever you need</Bullet>
      </SectionGroup>

      <SectionGroup title="About those permissions">
        <Bullet>Microphone: So you can give agent tasks naturally with your voice</Bullet>
        <Bullet>Accessibility: Lets Basil paste results and do helpful automations</Bullet>
      </SectionGroup>

      <SectionGroup title="Perfect for complex work">
        <Bullet>"Research this company and draft a personalized outreach email"</Bullet>
        <Bullet>"Analyze these meeting notes and create action items"</Bullet>
        <Bullet>"Find relevant background on this topic and write a brief"</Bullet>
        <Bullet>"Compare these two documents and highlight key differences"</Bullet>
      </SectionGroup>

      <SectionGroup title="For bigger tasks, Basil gets strategic">
        <Bullet>Complex requests get broken into smart steps with a clear action plan</Bullet>
        <Bullet>If something's unclear, Basil asks a quick question and keeps going</Bullet>
        <Bullet>You see everything happening in real-time — no mysterious waiting</Bullet>
      </SectionGroup>

      <SectionGroup title="Tips for best results">
        <Bullet>Keep what you want to work with visible on screen when you press the hotkey</Bullet>
        <Bullet>Be specific about style: "Make it friendly" or "Keep it brief"</Bullet>
        <Bullet>Wake word activation is in development for future hands-free operation</Bullet>
      </SectionGroup>

      <SectionGroup title="Add context with files and folders">
        <Bullet>Drag files or folders onto the agent task widget while speaking</Bullet>
        <Bullet>Dropped items appear as clickable "References" below your request</Bullet>
        <Bullet>Say things like "using these files" or "in this folder" — Basil will know what you mean</Bullet>
        <Bullet>Works for initial agent tasks and follow-up requests</Bullet>
      </SectionGroup>

      <SectionGroup title="About the hotkey">
        <Bullet>Default hotkey: ⌥+Space (Option+Space)</Bullet>
        <Bullet>Choose something comfortable for frequent use</Bullet>
        <Bullet>Customize anytime in Settings → Hotkeys</Bullet>
      </SectionGroup>
    </div>
  )
}
