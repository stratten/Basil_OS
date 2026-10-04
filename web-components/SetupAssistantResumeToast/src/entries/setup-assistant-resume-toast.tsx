import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../App'
import '../styles/panel.css'
import '../styles/resume-toast-surface-finish.css'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'

enableBackdropSurfaceFinish()

const root = document.getElementById('root')

if (!root) {
  throw new Error('Setup assistant resume toast root is missing')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
