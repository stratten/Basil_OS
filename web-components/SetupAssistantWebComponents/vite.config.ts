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
        'setup-assistant': 'src/entries/setup-assistant.html',
        'setup-permissions': 'src/entries/setup-permissions.html',
      },
    },
  },
})
