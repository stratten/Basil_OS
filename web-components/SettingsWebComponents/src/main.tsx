import { createRoot } from 'react-dom/client'
import './styles/settings-elements.css'
import { SettingsShell } from './app/SettingsShell'
import '@shared/webkit-window-chrome.css'
import '@shared/basil-window-chrome.css'
import '@shared/switch.css'
import '@shared/presence-motion.css'
import './styles/appearance-settings.css'
import './styles/profile-settings.css'
import './styles/memory-intelligence-settings.css'
import './styles/writing-examples-settings.css'
import './styles/models-settings.css'
import './styles/transcription-api-models.css'
import './styles/reasoning-api-models.css'
import './styles/custom-models.css'
import './styles/browser-automation-settings.css'
import './styles/reasoning-defaults-settings.css'
import './styles/skills-settings.css'
import './styles/activity-capture-settings.css'
import './styles/memories-settings.css'
import './styles/proactive-suggestions-settings.css'
import './styles/meetings-settings.css'
import './styles/settings-shell.css'
import './styles/home-settings.css'

const container = document.getElementById('root')
if (container) {
  createRoot(container).render(<SettingsShell />)
}
