import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/summary': { target: 'http://localhost:7070', changeOrigin: true },
      '/health': { target: 'http://localhost:7070', changeOrigin: true },
      '/services': { target: 'http://localhost:7070', changeOrigin: true },
      '/report': { target: 'http://localhost:7070', changeOrigin: true },
      '/config': { target: 'http://localhost:7070', changeOrigin: true },
      '/docker': { target: 'http://localhost:7070', changeOrigin: true },
    },
  },
})
