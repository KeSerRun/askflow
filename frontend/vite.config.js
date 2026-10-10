import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// 所有应用名称在此统一配置，修改后重新 build 生效
const APP_NAME = 'AskFlow'

// https://vite.dev/config/
export default defineConfig({
  base: './', // 设置基础路径为相对路径
  // 构建产物输出到 frontend/dist（相对 frontend 根）
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  plugins: [
    vue(),
    vueDevTools(),
  ],
  define: {
    'import.meta.env.VITE_APP_NAME': JSON.stringify(APP_NAME),
    'import.meta.env.VITE_APP_TITLE': JSON.stringify(APP_NAME),
  },
  // 配置路径别名
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  // 配置开发服务器
  server: {
    port: 5173, // 前端端口
    proxy: {
      // 这里的 '/api' 对应你 axios.post('/api/login') 中的 '/api'
      '/api': {
        target: 'http://127.0.0.1:11000', // 这里填写后端服务器的真实地址
        changeOrigin: true,              // 允许跨域
        // rewrite: (path) => path.replace(/^\/api/, '') // 如果后端接口不需要 /api 前缀，需开启此行重写
      }
    }
  }
})
