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
    },
  },
  server: {
    fs: {
      allow: [path.resolve(__dirname, '..')],
    },
  },
  build: {
    outDir: 'dist',
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
    ],
  },
})
