import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../App'
import '../styles/panel.css'

const root = document.getElementById('root')

if (!root) {
  throw new Error('Model download mini panel root is missing')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
