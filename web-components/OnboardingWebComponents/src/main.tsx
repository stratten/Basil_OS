import React from 'react'
import ReactDOM from 'react-dom/client'
import './styles.css'

// Development: show component gallery
import { UseCaseGallery } from './components/comparison/UseCaseGallery'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div className="min-h-screen bg-gradient-to-br from-blue-900 via-purple-900 to-indigo-900">
      <UseCaseGallery />
    </div>
  </React.StrictMode>,
)
