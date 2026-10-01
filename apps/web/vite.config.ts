/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The service serves the built app from the same origin as /v1 (ADR-017). In development the
// Vite server proxies /v1 to a local service so cookies, CSRF and Origin checks behave the same.
const service = process.env.DOCTRANSLATOR_DEV_SERVICE ?? 'http://127.0.0.1:8765'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/v1': { target: service, changeOrigin: false } },
  },
  // No data: URIs: the service's CSP allows fonts and images from 'self' only.
  build: { sourcemap: true, assetsInlineLimit: 0 },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
