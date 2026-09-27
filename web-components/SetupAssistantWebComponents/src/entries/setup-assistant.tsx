import React from 'react'
import { createRoot } from 'react-dom/client'

import { SetupAssistantApp } from '@/app/SetupAssistantApp'
import '@/styles/setup-assistant.css'

const root = document.getElementById('root')

if (!root) {
  throw new Error('Setup assistant root element was not found.')
}

createRoot(root).render(
  <React.StrictMode>
    <SetupAssistantApp />
  </React.StrictMode>,
)
