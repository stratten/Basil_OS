import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../App'
import '../styles/panel.css'
import '../styles/power-user-guide-surface-finish.css'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()

const root = document.getElementById('root')

if (!root) {
  throw new Error('Power User Guide panel root is missing')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
