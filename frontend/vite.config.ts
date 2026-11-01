import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const identity = env.IDENTITY_PROXY_TARGET || 'http://127.0.0.1:8000';
  const discussion = env.DISCUSSION_PROXY_TARGET || 'http://127.0.0.1:8001';
  const realtime = env.REALTIME_PROXY_TARGET || 'http://127.0.0.1:8002';
  return {
    plugins: [react()],
    server: {
      port: 5173, strictPort: true,
      proxy: {
        '/api/auth': { target: identity, changeOrigin: false },
        '/api/users': { target: identity, changeOrigin: false },
        '/api/admin': { target: identity, changeOrigin: false },
        '/api/forum': { target: discussion, changeOrigin: false },
        '/api/notifications': { target: realtime, changeOrigin: false },
        '/api/search': { target: env.SEARCH_PROXY_TARGET || 'http://127.0.0.1:8003', changeOrigin: false },
        '/ws': { target: realtime, ws: true, changeOrigin: false },
      },
    },
    test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', restoreMocks: true },
  };
});
