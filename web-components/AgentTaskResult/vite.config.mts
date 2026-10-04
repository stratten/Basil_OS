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
  test: {
    environment: 'jsdom',
    globals: true,
    include: [
      'src/**/*.{test,spec}.{ts,tsx}',
      '../shared/ExecutionDisclosureChevron.test.tsx',
      '../shared/appearanceTokenContract.test.ts',
      '../shared/webTheme.test.ts',
      '../shared/paletteFixtures.test.ts',
      '../shared/websocket/reconnectingWebSocket.test.ts',
      '../shared/vite/basilContentSecurityPolicy.test.ts',
      '../shared/usePresenceTransition.test.tsx',
      '../shared/PresenceRegion.test.tsx',
      '../shared/CrossfadeStack.test.tsx',
      '../shared/bubble/*.test.ts',
    ],
  },
  server: {
    fs: {
      allow: [path.resolve(import.meta.dirname, '..')],
    },
  },
  build: {
    outDir: 'dist',
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        'agent-task-result': 'src/entries/agent-task-result.html',
        'file-preview': 'src/entries/file-preview.html',
        'local-web-preview': 'src/entries/local-web-preview.html',
      },
      output: {
        assetFileNames: 'assets/agent-task-[name]-[hash][extname]',
      },
    },
  },
})
