export const PRIVACY_AND_DATA_FLOW_URL = 'https://github.com/stratten/Basil_OS/blob/main/docs/privacy-and-data-flow.md'

/** The plain-language promise about risky actions, with a way to read the full data-flow guide. */
export function IntroTrustNote() {
  return (
    <aside className="intro-trust-note" aria-label="How Basil handles risky actions">
      <strong>You approve risky actions first.</strong>
      <p>
        Anything that could change things outside Basil, like running a command, deleting a file or sending a message, waits for your approval. The approval card explains what the action does before you decide, and says so when the agent did not explain it. You can choose to remember an approval for a specific tool, and change that in Settings.
      </p>
      <p>
        <a href={PRIVACY_AND_DATA_FLOW_URL} target="_blank" rel="noreferrer">Read how Basil handles your data</a>
      </p>
    </aside>
  )
}
