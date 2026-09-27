import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '../App'
import '../styles/panel.css'

const root = document.getElementById('root')

if (!root) {
  throw new Error('Setup assistant resume toast root is missing')
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
