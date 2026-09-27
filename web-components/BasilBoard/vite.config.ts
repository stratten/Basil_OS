/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@shared': path.resolve(__dirname, '../shared'),
      '@agent-task': path.resolve(__dirname, '../AgentTaskResult/src'),
      'react/jsx-runtime': path.resolve(__dirname, './node_modules/react/jsx-runtime.js'),
      react: path.resolve(__dirname, './node_modules/react'),
    },
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
        'basil-board': 'src/entries/basil-board.html',
        'conversation': 'src/entries/conversation.html',
      },
      output: {
        assetFileNames: 'assets/basil-board-[name]-[hash][extname]',
      },
    },
  },
  test: {
    environment: 'jsdom',
    clearMocks: true,
    setupFiles: ['./src/test/setup.ts'],
  },
});
