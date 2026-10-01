import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { basilContentSecurityPolicy } from '../shared/vite/basilContentSecurityPolicy';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react(), basilContentSecurityPolicy()],
  base: './',
  build: {
    outDir: 'dist',
    assetsInlineLimit: 0,
    rollupOptions: {
      input: {
        'meeting-assistant': resolve(import.meta.dirname, 'src/entries/meeting-assistant.html'),
        'meeting-analysis': resolve(import.meta.dirname, 'src/entries/meeting-analysis.html'),
      },
      output: {
        assetFileNames: 'assets/meeting-[name]-[hash][extname]',
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(import.meta.dirname, 'src'),
      '@shared': resolve(import.meta.dirname, '../shared'),
      react: resolve(import.meta.dirname, 'node_modules/react'),
      'react/jsx-runtime': resolve(import.meta.dirname, 'node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': resolve(import.meta.dirname, 'node_modules/react/jsx-dev-runtime.js'),
      'react-dom': resolve(import.meta.dirname, 'node_modules/react-dom'),
    },
  },
  server: {
    fs: {
      allow: [resolve(import.meta.dirname, '..')],
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
});
