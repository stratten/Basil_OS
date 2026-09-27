import React from 'react';
import { createRoot } from 'react-dom/client';
import { ProfileEditorApp } from '../app/ProfileEditorApp';
import '../styles/profile-editor.css';
import type { ProfileEditorConfig } from '../types';

const fallbackConfig: ProfileEditorConfig = {
  mode: 'memory_file',
  identifier: 'user.md',
  apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
};

const config = window.basilProfileEditorConfig ?? fallbackConfig;
const root = document.getElementById('root');

if (!root) {
  throw new Error('Profile editor root element not found');
}

createRoot(root).render(
  <React.StrictMode>
    <ProfileEditorApp initialConfig={config} />
  </React.StrictMode>,
);
