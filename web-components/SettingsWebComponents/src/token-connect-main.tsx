import { createRoot } from 'react-dom/client'
import { TokenConnectApp } from './app/TokenConnectApp'
import '@shared/webkit-window-chrome.css'
import '@shared/basil-window-chrome.css'
import './styles/appearance-settings.css'
import './styles/settings-surface-finish.css'
import { installBlueprintReveal } from '@shared/blueprintController'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()
installBlueprintReveal()

const container = document.getElementById('root')
if (container) {
  createRoot(container).render(<TokenConnectApp />)
}
