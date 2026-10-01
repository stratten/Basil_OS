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
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        'skill-reconciliation-workspace': 'src/entries/skill-reconciliation-workspace.html',
      },
    },
  },
})
