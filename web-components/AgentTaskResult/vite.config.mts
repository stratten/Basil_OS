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
      '../shared/disclosure/ExecutionDisclosureChevron.test.tsx',
      '../shared/windowChrome/CircleControlIcons.test.tsx',
      '../shared/theme/appearanceTokenContract.test.ts',
      '../shared/theme/webTheme.test.ts',
      '../shared/theme/paletteFixtures.test.ts',
      '../shared/websocket/reconnectingWebSocket.test.ts',
      '../shared/status/BackendLivenessBanner.test.tsx',
      '../shared/vite/basilContentSecurityPolicy.test.ts',
      '../shared/motion/usePresenceTransition.test.tsx',
      '../shared/motion/PresenceRegion.test.tsx',
      '../shared/motion/CrossfadeStack.test.tsx',
      '../shared/history/useHistoryRowRevealDelete.test.tsx',
      '../shared/disclosure/useExpandableHeight.test.tsx',
      '../shared/disclosure/ExpandableList.test.tsx',
      '../shared/bubble/*.test.ts',
      '../shared/text/plainMarkdownText.test.ts',
      '../shared/tooltip/*.test.tsx',
      '../shared/teamIdentity.test.ts',
      '../shared/attachments/attachmentPaths.test.ts',
      '../shared/Attachment*.test.tsx',
      '../shared/icons/IconChipList.test.tsx',
      '../shared/icons/connectionIcons.test.ts',
      '../shared/search/*.test.{ts,tsx}',
      '../shared/historyFilters/*.test.{ts,tsx}',
      '../shared/inputs/TaskAutoApproveToggle.test.tsx',
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
