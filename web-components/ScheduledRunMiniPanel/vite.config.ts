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
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        'scheduled-run-mini-panel': 'src/entries/scheduled-run-mini-panel.html',
      },
    },
  },
})
