import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式下把 /api 代理到 FastAPI；生产环境由容器内 Nginx（或 compose）转发。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.VITE_BACKEND_URL || 'http://localhost:8000'
  return {
    plugins: [react()],
    server: {
      host: true,
      port: 5173,
      proxy: {
        '/api': {
          target: backend,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  }
})
