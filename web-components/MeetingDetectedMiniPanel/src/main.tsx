import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/panel.css'
import { installBlueprintReveal } from '@shared/blueprintController'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBlueprintReveal()
installBasilTooltips()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
