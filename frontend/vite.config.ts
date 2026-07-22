import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    proxy: {
      '/run': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
      '/health': 'http://127.0.0.1:8000',
      '/metrics': 'http://127.0.0.1:8000',
      '/inbox': 'http://127.0.0.1:8000',
      '/samples': 'http://127.0.0.1:8000',
      '/vendor-graph': 'http://127.0.0.1:8000',
      '/approve': 'http://127.0.0.1:8000',
      '/deny': 'http://127.0.0.1:8000',
      '/anomaly': 'http://127.0.0.1:8000',
      '/reviews': 'http://127.0.0.1:8000',
      '/escalations': 'http://127.0.0.1:8000',
      '/disputes': 'http://127.0.0.1:8000',
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
