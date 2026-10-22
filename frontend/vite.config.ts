import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 允许通过反向代理域名访问 dev server（Vite 5.4.12+ 默认拦截未知 Host，防 DNS rebinding）。
// 默认放行 store.qxkg.cn 与 .qxkg.cn（该域下所有子域，后续换子域无需再改配置）；
// 需要临时追加/覆盖时用环境变量：VITE_ALLOWED_HOSTS="a.com,b.com"（读 process.env，非 import.meta.env）。
// 注意：不要设 allowedHosts: true，等于关掉该防护。
const allowedHosts = (process.env.VITE_ALLOWED_HOSTS?.split(',').map((s) => s.trim()).filter(Boolean)) ?? [
  'store.qxkg.cn',
  '.qxkg.cn',
  'localhost',
]

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    allowedHosts,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
