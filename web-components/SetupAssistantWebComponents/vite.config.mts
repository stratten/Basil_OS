import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { basilContentSecurityPolicy } from '../shared/vite/basilContentSecurityPolicy'
import path from 'path'

export default defineConfig({
  plugins: [react(), basilContentSecurityPolicy()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
      '@shared': path.resolve(import.meta.dirname, '../shared'),
      'react/jsx-runtime': path.resolve(import.meta.dirname, './node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': path.resolve(import.meta.dirname, './node_modules/react/jsx-dev-runtime.js'),
      react: path.resolve(import.meta.dirname, './node_modules/react'),
      'react-dom': path.resolve(import.meta.dirname, './node_modules/react-dom'),
    },
  },
  server: {
    fs: {
      allow: [path.resolve(import.meta.dirname, '..')],
    },
  },
  test: {
    include: ['src/**/*.{test,spec}.{ts,tsx}', '../shared/motion/useStickToBottom.test.tsx', '../shared/contextImport/ContextImportPanel.test.tsx', '../shared/contextImport/ProfileImportPanel.test.tsx', '../shared/contextImport/ImportDialogs.test.tsx', '../shared/contextImport/ImportJobProgress.test.tsx', '../shared/contextImport/useContextImportJob.test.tsx', '../shared/contextImport/contextImportClient.test.ts', '../shared/dialogs/BasilModalDialog.test.tsx', '../shared/dialogs/basilModalDialog.contract.test.ts', '../shared/status/DownloadProgress.test.tsx'],
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        'setup-assistant': 'src/entries/setup-assistant.html',
        'setup-permissions': 'src/entries/setup-permissions.html',
      },
    },
  },
})
