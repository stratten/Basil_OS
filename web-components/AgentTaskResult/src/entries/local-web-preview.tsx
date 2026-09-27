import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import LocalWebPreviewApp from '../components/localWebPreview/LocalWebPreviewApp';
import '../styles/theme.css';
import '../styles/components.css';
import '../styles/components/local-web-preview.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <LocalWebPreviewApp />
  </StrictMode>
);
