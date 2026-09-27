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
  build: {
    outDir: 'dist',
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        'agent-task-capture-input': 'src/entries/agent-task-capture-input.html',
      },
      output: {
        assetFileNames: 'assets/agent-task-capture-[name]-[hash][extname]',
      },
    },
  },
})
