import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import FilePreviewApp from '../components/FilePreviewApp';
import '../styles/theme.css';
import '../styles/components.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <FilePreviewApp />
  </StrictMode>
);
