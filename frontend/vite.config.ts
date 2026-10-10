/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Default API port 8700 (scripts/dev.sh); 8000 is often taken by other local tools.
const apiTarget = process.env.JAMRECALL_API_URL ?? 'http://127.0.0.1:8700';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: Number(process.env.JAMRECALL_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: { '/api': apiTarget },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
  },
});
