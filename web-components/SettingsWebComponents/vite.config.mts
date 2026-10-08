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
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: [
      'src/**/*.{test,spec}.{ts,tsx}',
      '../shared/BasilWindowChrome.test.tsx',
      '../shared/ExecutionDisclosureChevron.test.tsx',
      '../shared/SettingsSubTabs.test.tsx',
      '../shared/useCollapseShortcut.test.tsx',
      '../shared/useSettledExpand.test.tsx',
      '../shared/swiftBridge.test.ts',
      '../shared/useCopyFeedback.test.tsx',
      '../shared/themeLayoutTokens.contract.test.ts',
      '../shared/WindowControlButton.test.tsx',
      '../shared/windowControlButton.contract.test.ts',
      '../shared/markdownSafety.test.ts',
      '../shared/InlineDeleteConfirm.test.tsx',
      '../shared/inlineDeleteConfirm.contract.test.ts',
      '../shared/formatClockSeconds.test.ts',
    ],
  },
})
