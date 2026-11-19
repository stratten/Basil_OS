import { createRoot } from 'react-dom/client'
import { TokenConnectApp } from './app/TokenConnectApp'
import '@shared/windowChrome/webkit-window-chrome.css'
import '@shared/windowChrome/basil-window-chrome.css'
import './styles/appearance-settings.css'
import './styles/settings-surface-finish.css'
import { installBlueprintReveal } from '@shared/blueprint/blueprintController'
import { enableBackdropSurfaceFinish } from '@shared/theme/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()
installBlueprintReveal()

const container = document.getElementById('root')
if (container) {
  createRoot(container).render(<TokenConnectApp />)
}
