import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  // Use relative paths for file:// protocol compatibility in WKWebView
  base: './',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // Output to dist folder - this gets bundled with the Swift app
    outDir: 'dist',
    // Generate a single HTML file with inlined CSS/JS for easy embedding
    rollupOptions: {
      input: {
        // Entry points for onboarding screens
        'single-demo': 'src/entries/single-demo.html',
        'onboarding-demo': 'src/entries/onboarding-demo.html',
        // Full gallery for training/exploration area
        'use-case-gallery': 'src/entries/use-case-gallery.html',
      },
    },
  },
})
