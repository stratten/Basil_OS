import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function Conversation() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="💬"
        title="Conversation"
        subtitle="An open-ended AI chat where you iterate, refine, and explore ideas over multiple turns — powered by the same writing partner Basil calls “Dill” elsewhere. Basil gives each capability a herb or spice nickname (like Dill and Paprika) so they're easy to talk about."
      />

      <SectionGroup title="What makes it special">
        <Bullet>Switch AI models mid-conversation — compare responses or use the best model for each task</Bullet>
        <Bullet>Persistent chat history lets you iterate and build on previous exchanges</Bullet>
        <Bullet>Streaming responses so you see progress in real-time</Bullet>
        <Bullet>Press your conversation hotkey (default: F8) to open the chat panel anytime</Bullet>
      </SectionGroup>

      <SectionGroup title="Good to know">
        <Bullet>No special permissions needed — just keyboard and mouse</Bullet>
        <Bullet>You control what the AI sees by pasting or typing content</Bullet>
        <Bullet>Conversation history stays local and private</Bullet>
      </SectionGroup>

      <SectionGroup title="Best for">
        <Bullet>Iterating on drafts: "Make this more formal" → "Now shorter" → "Perfect!"</Bullet>
        <Bullet>Exploring ideas through back-and-forth discussion</Bullet>
        <Bullet>Working with pasted content when you don't need screen context</Bullet>
        <Bullet>Comparing different AI model responses on the same question</Bullet>
      </SectionGroup>

      <SectionGroup title="About the hotkey">
        <Bullet>Default hotkey: F8</Bullet>
        <Bullet>Opens the chat panel instantly from anywhere</Bullet>
        <Bullet>Customize anytime in Settings → Hotkeys</Bullet>
      </SectionGroup>
    </div>
  )
}
