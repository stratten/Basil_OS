import { Bullet, SectionGroup, SectionHeader } from '../Bullet'

export default function AssistantSession() {
  return (
    <div className="pug-section">
      <SectionHeader
        icon="✨"
        title="Dill"
        subtitle="The smartest way to draft replies, summaries, and content — just tell Basil what you want"
      />

      <SectionGroup title="Here's the magic">
        <Bullet>Hit your suggestions hotkey — a widget pops up</Bullet>
        <Bullet>Say what you want: "Draft a reply saying yes to Tuesday" or "Summarize this in 3 bullets"</Bullet>
        <Bullet>While you speak, Basil reads what's on your screen and pairs it with your request</Bullet>
        <Bullet>Behind the scenes, Basil enhances your request to be clearer and more specific</Bullet>
        <Bullet>Watch your perfect draft appear in real-time</Bullet>
        <Bullet>One click to insert it exactly where you need it</Bullet>
      </SectionGroup>

      <SectionGroup title="About those permissions">
        <Bullet>Microphone: So you can speak naturally instead of typing</Bullet>
        <Bullet>Accessibility: Lets Basil paste your drafts seamlessly into any app</Bullet>
      </SectionGroup>

      <SectionGroup title="Perfect for quick tasks">
        <Bullet>"Draft a quick reply to this email accepting the meeting"</Bullet>
        <Bullet>"Summarize these bullet points into one sentence"</Bullet>
        <Bullet>"Make this paragraph more professional"</Bullet>
        <Bullet>"Translate this text to Spanish"</Bullet>
      </SectionGroup>

      <SectionGroup title="Tips for amazing results">
        <Bullet>Basil automatically reads your current app — no selection needed</Bullet>
        <Bullet>Unlike other tools, you never have to highlight text for Basil to understand context</Bullet>
        <Bullet>But if you want to narrow the focus, you can highlight specific text and it will prioritize that</Bullet>
        <Bullet>Be specific with your request: "Write a friendly reply accepting the Tuesday meeting"</Bullet>
      </SectionGroup>

      <SectionGroup title="About the hotkey">
        <Bullet>Default hotkey: ⌥+⌥ (double-tap Option)</Bullet>
        <Bullet>Quick and ergonomic - no awkward key combos</Bullet>
        <Bullet>Customize anytime in Settings → Hotkeys</Bullet>
      </SectionGroup>

      <SectionGroup title="Local vs. cloud models">
        <Bullet>Local models keep everything private and work without internet</Bullet>
        <Bullet>Cloud models (optional) know more about the world and stay up-to-date</Bullet>
        <Bullet>You can switch anytime in Settings — cloud usage goes to your own API account</Bullet>
      </SectionGroup>

      <SectionGroup title="Getting even smarter">
        <Bullet>Soon: Basil will learn from your past activities to match your natural writing tone</Bullet>
        <Bullet>The more you use it, the better it gets at sounding like you</Bullet>
      </SectionGroup>
    </div>
  )
}
