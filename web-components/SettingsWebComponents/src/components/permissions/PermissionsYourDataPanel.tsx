interface PermissionsYourDataPanelProps {
  /** Switches to the Application tab, which lists every permission macOS has given Basil and whether it is granted. */
  onShowGrantedPermissions: () => void
}

const DATA_LOCATIONS: readonly { path: string; holds: string }[] = [
  { path: '~/.basil', holds: 'Your conversations, knowledge database, meeting recordings, agent task history, settings, downloaded models, logs, and Basil\u2019s own sign-in details for the background service.' },
  { path: '~/.config/basil', holds: 'Setup assistant state and voice listener settings.' },
  { path: '~/Library/Application Support/Basil', holds: 'Recordings and captured data written by the released app.' },
  { path: '~/Library/Application Support/com.stratten.basil', holds: 'Background service logs, process files, and startup files.' },
  { path: 'Your Keychain', holds: 'Saved sign-ins, connection tokens, and API keys. Only Basil reads them.' },
]

const UNINSTALL_CHOICES: readonly { title: string; flag: string | null; result: string }[] = [
  { title: 'Everything', flag: null, result: 'Removes the app, all of your data, saved keys and sign-ins, settings, and the permissions macOS gave Basil. This is what double-clicking the uninstaller does.' },
  { title: 'The app only', flag: '--app-only', result: 'Removes the Basil app and leaves your data, saved keys, settings, and permissions alone. Installing Basil again picks up where you left off.' },
  { title: 'Your data only', flag: '--data-only', result: 'Removes your data, saved keys, settings, and permissions and leaves the app installed, so Basil starts fresh.' },
]

/** Where Basil keeps things, what the uninstaller removes, and how to see the permissions Basil has. It is information only: nothing on this page changes your files. */
export function PermissionsYourDataPanel({ onShowGrantedPermissions }: PermissionsYourDataPanelProps) {
  return (
    <section className="permissions-application-panel permissions-your-data-panel" aria-labelledby="permissions-your-data-heading">
      <header className="permissions-application-header">
        <div>
          <h2 id="permissions-your-data-heading">Your Data and Uninstall</h2>
          <p>Basil keeps your information on this Mac. This page shows where, what the permissions you gave it are, and how to remove Basil, its data, or both. Nothing on this page changes your files.</p>
        </div>
      </header>

      <div className="permissions-your-data-section">
        <h3>Where Basil keeps your files</h3>
        <ul className="permissions-your-data-list">
          {DATA_LOCATIONS.map((location) => (
            <li key={location.path}>
              <code>{location.path}</code>
              <span>{location.holds}</span>
            </li>
          ))}
        </ul>
        <p className="permissions-your-data-note">Files Basil made for you somewhere else, such as a document saved to your Desktop, stay where you put them.</p>
      </div>

      <div className="permissions-your-data-section">
        <h3>Permissions Basil has</h3>
        <p>macOS keeps the permissions you gave Basil, such as the microphone, Accessibility, and Screen Recording. The Application tab lists each one and whether it is granted. To take one back, turn Basil off for it in System Settings under Privacy and Security.</p>
        <button type="button" className="secondary-button" onClick={onShowGrantedPermissions}>
          See the permissions Basil has
        </button>
      </div>

      <div className="permissions-your-data-section">
        <h3>Uninstalling Basil</h3>
        <p>Uninstalling is done with <strong>Uninstall Basil.command</strong>, which is on the Basil disk image you installed from. If you no longer have the disk image, download it again and open it. The uninstaller is a plain text script you can open and read first. It shows everything it will remove, asks before it removes anything, and never touches files you made elsewhere.</p>
        <ul className="permissions-your-data-choices">
          {UNINSTALL_CHOICES.map((choice) => (
            <li key={choice.title}>
              <strong>{choice.title}</strong>
              {choice.flag ? <code>{choice.flag}</code> : <span className="permissions-your-data-default">Double-click it</span>}
              <span>{choice.result}</span>
            </li>
          ))}
        </ul>
        <p className="permissions-your-data-note">
          To use an option or preview first, run it in Terminal, for example <code>{'"/Volumes/Basil/Uninstall Basil.command" --dry-run'}</code>. Add <code>--keep-models</code> to keep the large downloaded models so you do not have to download them again.
        </p>
      </div>
    </section>
  )
}
