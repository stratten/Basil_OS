import { createRoot } from 'react-dom/client'
import './styles/settings-elements.css'
import { SettingsShell } from './app/SettingsShell'
import '@shared/windowChrome/webkit-window-chrome.css'
import '@shared/windowChrome/basil-window-chrome.css'
import '@shared/inputs/switch.css'
import '@shared/motion/presence-motion.css'
import '@shared/disclosure/expandable-clamp.css'
import '@shared/text/markdown-table.css'
import './styles/appearance-settings.css'
import './styles/profile-settings.css'
import './styles/memory-intelligence-settings.css'
import './styles/writing-examples-settings.css'
import './styles/models-settings.css'
import './styles/transcription-api-models.css'
import './styles/cloud-meeting-transcription.css'
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
import './styles/settings-surface-finish.css'
import { installBlueprintReveal } from '@shared/blueprint/blueprintController'
import { enableBackdropSurfaceFinish } from '@shared/theme/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()
installBlueprintReveal()

const container = document.getElementById('root')
if (container) {
  createRoot(container).render(<SettingsShell />)
}
