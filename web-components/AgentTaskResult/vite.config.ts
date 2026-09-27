import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
      'react/jsx-runtime': path.resolve(__dirname, './node_modules/react/jsx-runtime.js'),
      react: path.resolve(__dirname, './node_modules/react'),
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
    ],
  },
  server: {
    fs: {
      allow: [path.resolve(__dirname, '..')],
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
