/// <reference types="vitest/config" />
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
  build: {
    outDir: 'dist',
    // Loaded from the app bundle, not the network; warn only if the single Settings chunk grows well past its current ~540 kB.
    chunkSizeWarningLimit: 1024,
    rollupOptions: {
      input: {
        'appearance-settings': 'src/entries/appearance-settings.html',
        'token-connect': 'src/entries/token-connect.html',
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: [
      'src/**/*.{test,spec}.{ts,tsx}',
      '../shared/windowChrome/BasilWindowChrome.test.tsx',
      '../shared/disclosure/ExecutionDisclosureChevron.test.tsx',
      '../shared/inputs/SettingsSubTabs.test.tsx',
      '../shared/disclosure/useCollapseShortcut.test.tsx',
      '../shared/disclosure/useSettledExpand.test.tsx',
      '../shared/swiftBridge.test.ts',
      '../shared/useCopyFeedback.test.tsx',
      '../shared/theme/themeLayoutTokens.contract.test.ts',
      '../shared/theme/fontScale.contract.test.ts',
      '../shared/theme/semanticState.contract.test.ts',
      '../shared/windowChrome/WindowControlButton.test.tsx',
      '../shared/windowChrome/windowControlButton.contract.test.ts',
      '../shared/windowChrome/WindowMoveHandle.test.tsx',
      '../shared/windowChrome/windowMoveHandle.contract.test.ts',
      '../shared/text/markdownSafety.test.ts',
      '../shared/dialogs/InlineDeleteConfirm.test.tsx',
      '../shared/dialogs/inlineDeleteConfirm.contract.test.ts',
      '../shared/dialogs/ModalHeader.test.tsx',
      '../shared/format/formatClockSeconds.test.ts',
      '../shared/disclosure/ExpandableClamp.test.tsx',
      '../shared/contextImport/ContextImportPanel.test.tsx',
      '../shared/contextImport/ProfileImportPanel.test.tsx',
      '../shared/contextImport/ImportDialogs.test.tsx',
      '../shared/contextImport/ImportJobProgress.test.tsx',
      '../shared/contextImport/useContextImportJob.test.tsx',
      '../shared/contextImport/contextImportClient.test.ts',
      '../shared/inputs/Switch.test.tsx',
    ],
  },
})
