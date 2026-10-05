import React from 'react'
import { createRoot } from 'react-dom/client'

import { SetupWindowChrome } from '@/components/layout/SetupWindowChrome'
import { PermissionPreflight } from '@/components/permissions/PermissionPreflight'
import '@/styles/setup-assistant.css'
import '@/styles/setup-assistant-surface-finish.css'
import { enableBackdropSurfaceFinish } from '@shared/surfaceFinish'
import { installBasilTooltips } from '@shared/tooltip/basilTooltip'

enableBackdropSurfaceFinish()
installBasilTooltips()

const root = document.getElementById('root')

if (!root) {
  throw new Error('Setup permissions root element was not found.')
}

createRoot(root).render(
  <React.StrictMode>
    <SetupWindowChrome title="Basil Permissions">
      <PermissionPreflight />
    </SetupWindowChrome>
  </React.StrictMode>,
)
