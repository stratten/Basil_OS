/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { basilContentSecurityPolicy } from '../shared/vite/basilContentSecurityPolicy';
import path from 'path';

export default defineConfig({
  plugins: [react(), basilContentSecurityPolicy()],
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
      '@shared': path.resolve(import.meta.dirname, '../shared'),
      '@agent-task': path.resolve(import.meta.dirname, '../AgentTaskResult/src'),
      'react/jsx-runtime': path.resolve(import.meta.dirname, './node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': path.resolve(import.meta.dirname, './node_modules/react/jsx-dev-runtime.js'),
      react: path.resolve(import.meta.dirname, './node_modules/react'),
      'react-dom': path.resolve(import.meta.dirname, './node_modules/react-dom'),
    },
    dedupe: ['marked', 'highlight.js', 'dompurify'],
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
