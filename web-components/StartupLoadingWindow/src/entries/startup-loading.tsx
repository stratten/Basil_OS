import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../App'
import '../styles/panel.css'
import '../styles/startup-loading-surface-finish.css'
import { installBlueprintReveal } from '@shared/blueprintController'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBlueprintReveal()
installBasilTooltips()

const root = document.getElementById('root')

if (!root) {
  throw new Error('Startup loading window root is missing')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
