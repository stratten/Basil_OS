import React from 'react'
import { createRoot } from 'react-dom/client'

import { SetupAssistantApp } from '@/app/SetupAssistantApp'
import '@/styles/setup-assistant.css'
import '@/styles/setup-assistant-surface-finish.css'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()

const root = document.getElementById('root')

if (!root) {
  throw new Error('Setup assistant root element was not found.')
}

createRoot(root).render(
  <React.StrictMode>
    <SetupAssistantApp />
  </React.StrictMode>,
)
