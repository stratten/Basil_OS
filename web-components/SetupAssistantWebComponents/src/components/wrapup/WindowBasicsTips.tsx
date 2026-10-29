// Static, verified shortcuts. ⌘E is wired by `useCollapseShortcut` in these windows: Home, Dill, Paprika, Meeting Assistant, and the setup window itself. ⌘Enter submits from `RichTextComposer`.
export function WindowBasicsTips() {
  return (
    <section className="setup-wrapup-window-basics" aria-labelledby="setup-wrapup-window-basics-heading">
      <h2 id="setup-wrapup-window-basics-heading">Handy to know</h2>
      <ul>
        <li>
          <kbd>⌘E</kbd>
          <span>Collapses or expands one of Basil&apos;s floating windows (Home, Dill, Paprika, Meeting Assistant, and this one) so it stays out of the way without closing.</span>
        </li>
        <li>
          <kbd>⌘↵</kbd>
          <span>Sends your message from a Basil text box.</span>
        </li>
      </ul>
    </section>
  )
}
